#if defined(__linux__) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200809L
#endif

/*
 * Independent matrix-free verifier for Lueker's finite-history automaton.
 *
 * This file deliberately does not include or call upper_graph_builder.c.  It
 * evaluates the mathematical transition recurrence directly, looks each
 * accepted successor up in the supplied state set, and accumulates the fixed
 * point certificate row with overflow-safe unsigned 128-bit arithmetic.
 */

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#if !defined(__SIZEOF_INT128__) || __SIZEOF_INT128__ != 16
#error "upper_matrix_free.c requires a compiler with unsigned __int128"
#endif

#define MAX_HISTORY 15
#define MAX_LENGTH (2 * MAX_HISTORY)
#define MAX_GRID (MAX_LENGTH + 1)
#define NOT_FOUND UINT32_MAX
#define REJECT_INDEX UINT32_MAX

enum failure_code {
    FAILURE_NONE = 0,
    FAILURE_STATE_ENCODING = 1,
    FAILURE_TRANSITION_INTERNAL = 2,
    FAILURE_MISSING_SUCCESSOR = 3,
    FAILURE_WITNESS_ZERO = 4,
    FAILURE_WITNESS_SCALE = 5,
    FAILURE_ROW_OVERFLOW = 6,
    FAILURE_INEQUALITY = 7,
    FAILURE_INDEX_CORRUPT = 8
};

typedef struct {
    int fd;
    void *address;
    size_t length;
} Mapping;

typedef struct {
    int history;
    const uint64_t *states;
    uint64_t state_count;
    const uint32_t *index;
    uint64_t index_capacity;
    const uint32_t *witness;
    const uint64_t *weights;
    uint64_t lambda_numerator;
    uint64_t witness_scale;
    uint64_t start;
    uint64_t end;
    uint64_t output_start;
    uint32_t *transition_output;
    uint64_t accepted;
    uint64_t rejected;
    uint64_t maximum_ceiling;
    uint64_t minimum_floor;
    uint64_t raw_maximum;
    uint64_t witness_minimum;
    uint64_t witness_maximum;
    int failure;
    uint64_t failure_row;
    int failure_column;
    uint64_t failure_lhs;
    uint64_t failure_rhs;
} Worker;

static void die(const char *message) {
    fprintf(stderr, "upper_matrix_free: %s\n", message);
    exit(2);
}

static void die_errno(const char *message) {
    fprintf(stderr, "upper_matrix_free: %s: %s\n", message, strerror(errno));
    exit(2);
}

static uint64_t parse_u64(const char *text, const char *name) {
    char *end = NULL;
    errno = 0;
    uint64_t value = strtoull(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0') {
        fprintf(stderr, "upper_matrix_free: invalid %s\n", name);
        exit(2);
    }
    return value;
}

static int parse_history(const char *text) {
    uint64_t value = parse_u64(text, "history");
    if (value < 2 || value > MAX_HISTORY) die("history must lie in [2,15]");
    return (int)value;
}

static int host_is_little_endian(void) {
    const uint16_t one = UINT16_C(1);
    return *((const uint8_t *)&one) == UINT8_C(1);
}

static uint64_t process_peak_rss_bytes(void) {
    struct rusage usage;
    if (getrusage(RUSAGE_SELF, &usage) != 0) die_errno("getrusage failed");
#ifdef __APPLE__
    return (uint64_t)usage.ru_maxrss;
#else
    return (uint64_t)usage.ru_maxrss * 1024;
#endif
}

static uint64_t file_size(int fd, const char *name) {
    struct stat status;
    if (fstat(fd, &status) != 0) die_errno(name);
    if (status.st_size < 0) die("negative file size");
    return (uint64_t)status.st_size;
}

static Mapping map_file(const char *path, int writable, uint64_t expected_size) {
    int flags = writable ? O_RDWR : O_RDONLY;
    int fd = open(path, flags);
    if (fd < 0) die_errno("cannot open mapped file");
    uint64_t actual = file_size(fd, "cannot stat mapped file");
    if (actual != expected_size || expected_size == 0 || expected_size > SIZE_MAX) {
        close(fd);
        die("mapped file size mismatch");
    }
    int protection = PROT_READ | (writable ? PROT_WRITE : 0);
    void *address = mmap(NULL, (size_t)expected_size, protection, MAP_SHARED, fd, 0);
    if (address == MAP_FAILED) {
        close(fd);
        die_errno("cannot mmap file");
    }
    Mapping result = {fd, address, (size_t)expected_size};
    return result;
}

static void unmap_file(Mapping *mapping) {
    if (munmap(mapping->address, mapping->length) != 0) die_errno("cannot unmap file");
    if (close(mapping->fd) != 0) die_errno("cannot close mapped file");
    mapping->address = NULL;
    mapping->length = 0;
    mapping->fd = -1;
}

static uint64_t mix64(uint64_t value) {
    value ^= value >> 30;
    value *= UINT64_C(0xbf58476d1ce4e5b9);
    value ^= value >> 27;
    value *= UINT64_C(0x94d049bb133111eb);
    value ^= value >> 31;
    return value;
}

static uint32_t lookup_state(const uint64_t *states, uint64_t state_count,
                             const uint32_t *index, uint64_t capacity,
                             uint64_t key, int *corrupt) {
    uint64_t slot = mix64(key) & (capacity - 1);
    for (uint64_t probes = 0; probes < capacity; ++probes) {
        uint32_t stored = index[slot];
        if (stored == 0) return NOT_FOUND;
        uint64_t state_number = (uint64_t)stored - 1;
        if (state_number >= state_count) {
            *corrupt = 1;
            return NOT_FOUND;
        }
        if (states[state_number] == key) return (uint32_t)state_number;
        slot = (slot + 1) & (capacity - 1);
    }
    *corrupt = 1;
    return NOT_FOUND;
}

static int canonical_encoding(uint64_t packed, int history) {
    unsigned bits = (unsigned)(4 * history);
    if (bits < 64 && (packed >> bits) != 0) return 0;
    uint64_t mask = (UINT64_C(1) << history) - 1;
    uint64_t x = packed & mask;
    return x < (UINT64_C(1) << (history - 1));
}

static uint64_t pack_state(uint32_t x, uint32_t y, uint32_t dx, uint32_t dy,
                           int history) {
    return (uint64_t)x | ((uint64_t)y << history) |
           ((uint64_t)dx << (2 * history)) |
           ((uint64_t)dy << (3 * history));
}

static uint32_t suffix(const uint8_t *word, int length, int history) {
    uint32_t result = 0;
    for (int offset = length - history; offset < length; ++offset)
        result = (result << 1) | (uint32_t)word[offset];
    return result;
}

/*
 * Evaluate the transition specification using a verifier-owned dynamic
 * program.  Strings are zero-indexed and the boundary reconstruction is kept
 * separate from the builder's one-indexed implementation.
 */
static int oracle_transition(uint64_t packed, int character, int padding,
                             int history, uint64_t *successor) {
    uint64_t mask = (UINT64_C(1) << history) - 1;
    uint32_t x = (uint32_t)(packed & mask);
    uint32_t y = (uint32_t)((packed >> history) & mask);
    uint32_t vertical = (uint32_t)((packed >> (2 * history)) & mask);
    uint32_t horizontal = (uint32_t)((packed >> (3 * history)) & mask);
    uint8_t top[MAX_LENGTH] = {0};
    uint8_t bottom[MAX_LENGTH] = {0};
    int16_t score[MAX_GRID][MAX_GRID];
    memset(score, 0, sizeof(score));

    for (int offset = 0; offset < history; ++offset) {
        int shift = history - 1 - offset;
        top[offset] = (uint8_t)((x >> shift) & 1U);
        bottom[offset] = (uint8_t)((y >> shift) & 1U);
    }

    score[history][history] = (int16_t)history;
    for (int row = history - 1; row >= 0; --row) {
        int bit = history - 1 - row;
        score[row][history] =
            (int16_t)(score[row + 1][history] - ((vertical >> bit) & 1U));
    }
    for (int column = history - 1; column >= 0; --column) {
        int bit = history - 1 - column;
        score[history][column] =
            (int16_t)(score[history][column + 1] - ((horizontal >> bit) & 1U));
    }

    int top_length = history;
    int bottom_length = history;
    uint8_t opposite = (uint8_t)(1 - character);
    if (padding > 0) {
        for (int count = 0; count < padding; ++count) top[top_length++] = opposite;
    } else if (padding < 0) {
        for (int count = 0; count < -padding; ++count)
            bottom[bottom_length++] = opposite;
    }
    top[top_length++] = (uint8_t)character;
    bottom[bottom_length++] = (uint8_t)character;

    for (int column = history + 1; column <= bottom_length; ++column)
        score[0][column] = score[0][column - 1];
    for (int row = history + 1; row <= top_length; ++row)
        score[row][0] = score[row - 1][0];

    for (int row = 1; row <= top_length; ++row) {
        for (int column = 1; column <= bottom_length; ++column) {
            if (row <= history && column <= history) continue;
            if (top[row - 1] == bottom[column - 1]) {
                score[row][column] = (int16_t)(score[row - 1][column - 1] + 1);
            } else {
                int16_t above = score[row - 1][column];
                int16_t left = score[row][column - 1];
                score[row][column] = above > left ? above : left;
            }
        }
    }

    int row = top_length;
    int column = bottom_length;
    int matches = 0;
    while (row >= history && column >= history) {
        if (score[row][column] == score[row - 1][column]) {
            --row;
        } else if (score[row][column] == score[row][column - 1]) {
            --column;
        } else if (score[row][column] == score[row - 1][column - 1] + 1) {
            --row;
            --column;
            ++matches;
        } else {
            return -1;
        }
        if (row == history && column == history) {
            if (matches != 1) return -1;
            uint32_t new_x = suffix(top, top_length, history);
            uint32_t new_y = suffix(bottom, bottom_length, history);
            uint32_t new_vertical = 0;
            uint32_t new_horizontal = 0;
            for (int rr = top_length - history + 1; rr <= top_length; ++rr) {
                int difference = score[rr][bottom_length] - score[rr - 1][bottom_length];
                if (difference < 0 || difference > 1) return -1;
                new_vertical = (new_vertical << 1) | (uint32_t)difference;
            }
            for (int cc = bottom_length - history + 1; cc <= bottom_length; ++cc) {
                int difference = score[top_length][cc] - score[top_length][cc - 1];
                if (difference < 0 || difference > 1) return -1;
                new_horizontal = (new_horizontal << 1) | (uint32_t)difference;
            }
            if (new_x >= (UINT32_C(1) << (history - 1))) {
                uint32_t word_mask = (UINT32_C(1) << history) - 1;
                new_x = word_mask - new_x;
                new_y = word_mask - new_y;
            }
            *successor = pack_state(new_x, new_y, new_vertical, new_horizontal, history);
            return 1;
        }
    }
    return 0;
}

static const char *failure_name(int failure) {
    switch (failure) {
        case FAILURE_STATE_ENCODING: return "state_encoding";
        case FAILURE_TRANSITION_INTERNAL: return "transition_internal";
        case FAILURE_MISSING_SUCCESSOR: return "missing_successor";
        case FAILURE_WITNESS_ZERO: return "witness_zero";
        case FAILURE_WITNESS_SCALE: return "witness_scale";
        case FAILURE_ROW_OVERFLOW: return "row_overflow";
        case FAILURE_INEQUALITY: return "inequality";
        case FAILURE_INDEX_CORRUPT: return "index_corrupt";
        default: return "none";
    }
}

static void record_failure(Worker *worker, int failure, uint64_t row, int column,
                           uint64_t lhs, uint64_t rhs) {
    if (worker->failure == FAILURE_NONE || row < worker->failure_row ||
        (row == worker->failure_row &&
         (failure < worker->failure ||
          (failure == worker->failure && column < worker->failure_column)))) {
        worker->failure = failure;
        worker->failure_row = row;
        worker->failure_column = column;
        worker->failure_lhs = lhs;
        worker->failure_rhs = rhs;
    }
}

static void *run_worker(void *argument) {
    Worker *worker = (Worker *)argument;
    int columns = 2 * (2 * worker->history - 1);
    worker->minimum_floor = UINT64_MAX;
    worker->witness_minimum = UINT64_MAX;
    worker->failure_row = UINT64_MAX;
    worker->failure_column = -1;
    for (uint64_t row = worker->start; row < worker->end; ++row) {
        uint64_t packed = worker->states[row];
        if (!canonical_encoding(packed, worker->history)) {
            record_failure(worker, FAILURE_STATE_ENCODING, row, -1, 0, 0);
            continue;
        }
        uint64_t witness_value = worker->witness == NULL ? 0 : worker->witness[row];
        if (worker->witness != NULL) {
            if (witness_value == 0) {
                record_failure(worker, FAILURE_WITNESS_ZERO, row, -1, 0, 0);
                continue;
            }
            if (witness_value > worker->witness_scale) {
                record_failure(worker, FAILURE_WITNESS_SCALE, row, -1,
                               witness_value, worker->witness_scale);
                continue;
            }
            if (witness_value < worker->witness_minimum)
                worker->witness_minimum = witness_value;
            if (witness_value > worker->witness_maximum)
                worker->witness_maximum = witness_value;
        }

        unsigned __int128 total = 0;
        int column_number = 0;
        for (int character = 0; character < 2; ++character) {
            for (int padding = -(worker->history - 1);
                 padding <= worker->history - 1; ++padding, ++column_number) {
                uint64_t successor_key = 0;
                int transition_status = oracle_transition(
                    packed, character, padding, worker->history, &successor_key);
                if (transition_status < 0) {
                    record_failure(worker, FAILURE_TRANSITION_INTERNAL, row,
                                   column_number, 0, 0);
                    if (worker->transition_output != NULL)
                        worker->transition_output[(row - worker->output_start) * (uint64_t)columns +
                                                  (uint64_t)column_number] = REJECT_INDEX;
                    continue;
                }
                if (transition_status == 0) {
                    ++worker->rejected;
                    if (worker->transition_output != NULL)
                        worker->transition_output[(row - worker->output_start) * (uint64_t)columns +
                                                  (uint64_t)column_number] = REJECT_INDEX;
                    continue;
                }
                int corrupt = 0;
                uint32_t successor = lookup_state(
                    worker->states, worker->state_count, worker->index,
                    worker->index_capacity, successor_key, &corrupt);
                if (corrupt) {
                    record_failure(worker, FAILURE_INDEX_CORRUPT, row,
                                   column_number, 0, 0);
                    continue;
                }
                if (successor == NOT_FOUND) {
                    record_failure(worker, FAILURE_MISSING_SUCCESSOR, row,
                                   column_number, 0, 0);
                    continue;
                }
                ++worker->accepted;
                if (worker->transition_output != NULL)
                    worker->transition_output[(row - worker->output_start) * (uint64_t)columns +
                                              (uint64_t)column_number] = successor;
                if (worker->witness != NULL) {
                    total += (unsigned __int128)worker->weights[column_number] *
                             (unsigned __int128)worker->witness[successor];
                }
            }
        }
        if (column_number != columns) {
            record_failure(worker, FAILURE_TRANSITION_INTERNAL, row, -1, 0, 0);
            continue;
        }
        if (worker->witness == NULL) continue;
        if (total > UINT64_MAX) {
            record_failure(worker, FAILURE_ROW_OVERFLOW, row, -1,
                           UINT64_MAX, UINT64_MAX);
            continue;
        }
        uint64_t total_u64 = (uint64_t)total;
        if (total_u64 > worker->raw_maximum) worker->raw_maximum = total_u64;
        uint64_t floor = total_u64 / witness_value;
        uint64_t ceiling = floor + (uint64_t)(total_u64 % witness_value != 0);
        if (ceiling > worker->maximum_ceiling) worker->maximum_ceiling = ceiling;
        if (floor < worker->minimum_floor) worker->minimum_floor = floor;
        unsigned __int128 rhs = (unsigned __int128)worker->lambda_numerator *
                                (unsigned __int128)witness_value;
        if (total > rhs) {
            record_failure(worker, FAILURE_INEQUALITY, row, -1, total_u64,
                           rhs > UINT64_MAX ? UINT64_MAX : (uint64_t)rhs);
        }
    }
    return NULL;
}

static Worker *run_parallel(Worker prototype, uint64_t start, uint64_t end,
                            int thread_count) {
    if (thread_count < 1 || thread_count > 1024) die("invalid thread count");
    Worker *workers = calloc((size_t)thread_count, sizeof(*workers));
    pthread_t *threads = calloc((size_t)thread_count, sizeof(*threads));
    if (workers == NULL || threads == NULL) die_errno("cannot allocate worker state");
    uint64_t rows = end - start;
    for (int number = 0; number < thread_count; ++number) {
        workers[number] = prototype;
        workers[number].start = start + rows * (uint64_t)number / (uint64_t)thread_count;
        workers[number].end = start + rows * (uint64_t)(number + 1) / (uint64_t)thread_count;
        if (pthread_create(&threads[number], NULL, run_worker, &workers[number]) != 0)
            die_errno("cannot start verifier thread");
    }
    for (int number = 0; number < thread_count; ++number) {
        if (pthread_join(threads[number], NULL) != 0)
            die_errno("cannot join verifier thread");
    }
    free(threads);
    return workers;
}

static Worker combine_workers(Worker *workers, int thread_count) {
    Worker combined;
    memset(&combined, 0, sizeof(combined));
    combined.minimum_floor = UINT64_MAX;
    combined.witness_minimum = UINT64_MAX;
    combined.failure_row = UINT64_MAX;
    combined.failure_column = -1;
    for (int number = 0; number < thread_count; ++number) {
        Worker *current = &workers[number];
        combined.accepted += current->accepted;
        combined.rejected += current->rejected;
        if (current->maximum_ceiling > combined.maximum_ceiling)
            combined.maximum_ceiling = current->maximum_ceiling;
        if (current->minimum_floor < combined.minimum_floor)
            combined.minimum_floor = current->minimum_floor;
        if (current->raw_maximum > combined.raw_maximum)
            combined.raw_maximum = current->raw_maximum;
        if (current->witness_minimum < combined.witness_minimum)
            combined.witness_minimum = current->witness_minimum;
        if (current->witness_maximum > combined.witness_maximum)
            combined.witness_maximum = current->witness_maximum;
        if (current->failure != FAILURE_NONE &&
            (combined.failure == FAILURE_NONE || current->failure_row < combined.failure_row ||
             (current->failure_row == combined.failure_row &&
              (current->failure < combined.failure ||
               (current->failure == combined.failure &&
                current->failure_column < combined.failure_column))))) {
            combined.failure = current->failure;
            combined.failure_row = current->failure_row;
            combined.failure_column = current->failure_column;
            combined.failure_lhs = current->failure_lhs;
            combined.failure_rhs = current->failure_rhs;
        }
    }
    return combined;
}

static void validate_common_dimensions(uint64_t state_count, uint64_t capacity) {
    if (state_count == 0 || state_count >= UINT32_MAX)
        die("state count must fit the uint32 index domain");
    if (capacity == 0 || (capacity & (capacity - 1)) != 0 ||
        capacity > SIZE_MAX / sizeof(uint32_t))
        die("index capacity must be a representable power of two");
    if ((unsigned __int128)state_count * 100 >=
        (unsigned __int128)capacity * 84)
        die("index load must be below 84 percent");
}

static int command_index(int argc, char **argv) {
    if (argc != 7)
        die("usage: upper_matrix_free index HISTORY STATES COUNT INDEX CAPACITY");
    int history = parse_history(argv[2]);
    uint64_t count = parse_u64(argv[4], "state count");
    uint64_t capacity = parse_u64(argv[6], "index capacity");
    validate_common_dimensions(count, capacity);
    if (count > SIZE_MAX / sizeof(uint64_t)) die("state mapping is too large");
    Mapping states_map = map_file(argv[3], 0, count * sizeof(uint64_t));
    const uint64_t *states = (const uint64_t *)states_map.address;

    int index_fd = open(argv[5], O_RDWR | O_CREAT | O_EXCL, 0600);
    if (index_fd < 0) die_errno("cannot create index file");
    uint64_t index_bytes = capacity * sizeof(uint32_t);
    if (index_bytes > INT64_MAX || ftruncate(index_fd, (off_t)index_bytes) != 0)
        die_errno("cannot size index file");
    uint32_t *index = mmap(NULL, (size_t)index_bytes, PROT_READ | PROT_WRITE,
                           MAP_SHARED, index_fd, 0);
    if (index == MAP_FAILED) die_errno("cannot mmap index file");

    uint64_t duplicate = UINT64_MAX;
    uint64_t invalid = UINT64_MAX;
    for (uint64_t state_number = 0; state_number < count; ++state_number) {
        uint64_t key = states[state_number];
        if (!canonical_encoding(key, history)) {
            invalid = state_number;
            break;
        }
        uint64_t slot = mix64(key) & (capacity - 1);
        while (index[slot] != 0) {
            uint64_t existing = (uint64_t)index[slot] - 1;
            if (existing >= count) die("new index contains an invalid entry");
            if (states[existing] == key) {
                duplicate = state_number;
                break;
            }
            slot = (slot + 1) & (capacity - 1);
        }
        if (duplicate != UINT64_MAX) break;
        index[slot] = (uint32_t)(state_number + 1);
    }

    uint32_t word_mask = (UINT32_C(1) << history) - 1;
    uint64_t initial = pack_state(0, 0, word_mask, word_mask, history);
    int corrupt = 0;
    uint32_t initial_number = lookup_state(states, count, index, capacity, initial, &corrupt);
    int passed = duplicate == UINT64_MAX && invalid == UINT64_MAX && !corrupt &&
                 initial_number != NOT_FOUND;
    if (passed) {
        if (msync(index, (size_t)index_bytes, MS_SYNC) != 0 || fsync(index_fd) != 0)
            die_errno("cannot sync completed index");
    }
    if (munmap(index, (size_t)index_bytes) != 0 || close(index_fd) != 0)
        die_errno("cannot close index file");
    unmap_file(&states_map);

    if (!passed) {
        printf("{\"status\":\"FAIL\",\"duplicate_state\":%" PRIu64
               ",\"invalid_state\":%" PRIu64
               ",\"initial_state_present\":%s}\n",
               duplicate, invalid, initial_number == NOT_FOUND ? "false" : "true");
        return 1;
    }
    printf("{\"status\":\"PASS\",\"states\":%" PRIu64
           ",\"capacity\":%" PRIu64
           ",\"initial_state_index\":%" PRIu32
           ",\"peak_rss_bytes\":%" PRIu64 "}\n",
           count, capacity, initial_number, process_peak_rss_bytes());
    return 0;
}

static void map_state_and_index(const char *states_path, uint64_t count,
                                const char *index_path, uint64_t capacity,
                                Mapping *states_map, Mapping *index_map) {
    validate_common_dimensions(count, capacity);
    if (count > SIZE_MAX / sizeof(uint64_t)) die("state mapping is too large");
    *states_map = map_file(states_path, 0, count * sizeof(uint64_t));
    *index_map = map_file(index_path, 0, capacity * sizeof(uint32_t));
}

static int command_dump(int argc, char **argv) {
    if (argc != 11)
        die("usage: upper_matrix_free dump HISTORY STATES COUNT INDEX CAPACITY START END THREADS OUTPUT");
    int history = parse_history(argv[2]);
    uint64_t count = parse_u64(argv[4], "state count");
    uint64_t capacity = parse_u64(argv[6], "index capacity");
    uint64_t start = parse_u64(argv[7], "start row");
    uint64_t end = parse_u64(argv[8], "end row");
    uint64_t thread_value = parse_u64(argv[9], "thread count");
    if (start > end || end > count || thread_value > INT32_MAX)
        die("invalid dump range or thread count");
    int thread_count = (int)thread_value;
    Mapping states_map, index_map;
    map_state_and_index(argv[3], count, argv[5], capacity, &states_map, &index_map);

    int columns = 2 * (2 * history - 1);
    unsigned __int128 output_size_128 = (unsigned __int128)(end - start) *
                                        (unsigned)columns * sizeof(uint32_t);
    if (output_size_128 == 0 || output_size_128 > INT64_MAX || output_size_128 > SIZE_MAX)
        die("transition diagnostic output is too large or empty");
    uint64_t output_size = (uint64_t)output_size_128;
    int output_fd = open(argv[10], O_RDWR | O_CREAT | O_EXCL, 0600);
    if (output_fd < 0 || ftruncate(output_fd, (off_t)output_size) != 0)
        die_errno("cannot create transition diagnostic output");
    uint32_t *output = mmap(NULL, (size_t)output_size, PROT_READ | PROT_WRITE,
                            MAP_SHARED, output_fd, 0);
    if (output == MAP_FAILED) die_errno("cannot mmap transition diagnostic output");
    Worker prototype;
    memset(&prototype, 0, sizeof(prototype));
    prototype.history = history;
    prototype.states = (const uint64_t *)states_map.address;
    prototype.state_count = count;
    prototype.index = (const uint32_t *)index_map.address;
    prototype.index_capacity = capacity;
    prototype.transition_output = output;
    prototype.output_start = start;
    Worker *workers = run_parallel(prototype, start, end, thread_count);
    Worker combined = combine_workers(workers, thread_count);
    free(workers);
    if (msync(output, (size_t)output_size, MS_SYNC) != 0 || fsync(output_fd) != 0)
        die_errno("cannot sync transition diagnostic output");
    if (munmap(output, (size_t)output_size) != 0 || close(output_fd) != 0)
        die_errno("cannot close transition diagnostic output");
    unmap_file(&index_map);
    unmap_file(&states_map);
    if (combined.failure != FAILURE_NONE) {
        printf("{\"status\":\"FAIL\",\"failure\":\"%s\",\"failure_row\":%" PRIu64
               ",\"failure_column\":%d}\n",
               failure_name(combined.failure), combined.failure_row,
               combined.failure_column);
        return 1;
    }
    printf("{\"status\":\"PASS\",\"rows\":%" PRIu64
           ",\"accepted_transitions\":%" PRIu64
           ",\"rejected_transitions\":%" PRIu64
           ",\"peak_rss_bytes\":%" PRIu64 "}\n",
           end - start, combined.accepted, combined.rejected,
           process_peak_rss_bytes());
    return 0;
}

static int command_scan(int argc, char **argv) {
    if (argc < 15)
        die("usage: upper_matrix_free scan HISTORY STATES COUNT INDEX CAPACITY WITNESS OFFSET START END THREADS LAMBDA WITNESS_SCALE WEIGHT...");
    int history = parse_history(argv[2]);
    int columns = 2 * (2 * history - 1);
    if (argc != 14 + columns) die("wrong number of fixed-point weights");
    uint64_t count = parse_u64(argv[4], "state count");
    uint64_t capacity = parse_u64(argv[6], "index capacity");
    uint64_t witness_offset = parse_u64(argv[8], "witness offset");
    uint64_t start = parse_u64(argv[9], "start row");
    uint64_t end = parse_u64(argv[10], "end row");
    uint64_t thread_value = parse_u64(argv[11], "thread count");
    uint64_t lambda = parse_u64(argv[12], "lambda numerator");
    uint64_t witness_scale = parse_u64(argv[13], "witness scale");
    if (start > end || end > count || start == end || thread_value > INT32_MAX ||
        lambda == 0 || witness_scale == 0 || witness_scale > UINT32_MAX)
        die("invalid scan dimensions or certificate parameters");
    int thread_count = (int)thread_value;
    uint64_t weights[2 * (2 * MAX_HISTORY - 1)];
    for (int column = 0; column < columns; ++column)
        weights[column] = parse_u64(argv[14 + column], "weight");

    Mapping states_map, index_map;
    map_state_and_index(argv[3], count, argv[5], capacity, &states_map, &index_map);
    if (witness_offset > UINT64_MAX - count * sizeof(uint32_t))
        die("witness mapping size overflow");
    uint64_t witness_size = witness_offset + count * sizeof(uint32_t);
    Mapping witness_map = map_file(argv[7], 0, witness_size);
    const uint8_t *witness_bytes = (const uint8_t *)witness_map.address;
    if (witness_offset % _Alignof(uint32_t) != 0)
        die("witness data is not uint32 aligned");

    Worker prototype;
    memset(&prototype, 0, sizeof(prototype));
    prototype.history = history;
    prototype.states = (const uint64_t *)states_map.address;
    prototype.state_count = count;
    prototype.index = (const uint32_t *)index_map.address;
    prototype.index_capacity = capacity;
    prototype.witness = (const uint32_t *)(witness_bytes + witness_offset);
    prototype.weights = weights;
    prototype.lambda_numerator = lambda;
    prototype.witness_scale = witness_scale;
    Worker *workers = run_parallel(prototype, start, end, thread_count);
    Worker combined = combine_workers(workers, thread_count);
    free(workers);
    unmap_file(&witness_map);
    unmap_file(&index_map);
    unmap_file(&states_map);

    if (combined.failure != FAILURE_NONE) {
        printf("{\"status\":\"FAIL\",\"failure\":\"%s\",\"failure_row\":%" PRIu64
               ",\"failure_column\":%d,\"lhs\":%" PRIu64
               ",\"rhs\":%" PRIu64 "}\n",
               failure_name(combined.failure), combined.failure_row,
               combined.failure_column, combined.failure_lhs,
               combined.failure_rhs);
        return 1;
    }
    printf("{\"status\":\"PASS\",\"start_row\":%" PRIu64
           ",\"end_row\":%" PRIu64
           ",\"rows\":%" PRIu64
           ",\"accepted_transitions\":%" PRIu64
           ",\"rejected_transitions\":%" PRIu64
           ",\"maximum_ceiling\":%" PRIu64
           ",\"minimum_floor\":%" PRIu64
           ",\"raw_maximum\":%" PRIu64
           ",\"witness_minimum\":%" PRIu64
           ",\"witness_maximum\":%" PRIu64
           ",\"peak_rss_bytes\":%" PRIu64 "}\n",
           start, end, end - start, combined.accepted, combined.rejected,
           combined.maximum_ceiling, combined.minimum_floor,
           combined.raw_maximum, combined.witness_minimum,
           combined.witness_maximum, process_peak_rss_bytes());
    return 0;
}

int main(int argc, char **argv) {
    if (!host_is_little_endian())
        die("the authenticated artifact format requires a little-endian host");
    if (argc < 2) die("expected index, dump, or scan command");
    if (strcmp(argv[1], "index") == 0) return command_index(argc, argv);
    if (strcmp(argv[1], "dump") == 0) return command_dump(argc, argv);
    if (strcmp(argv[1], "scan") == 0) return command_scan(argc, argv);
    die("unknown command (expected index, dump, or scan)");
    return 2;
}
