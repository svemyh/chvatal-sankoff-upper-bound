#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>

#define MAX_H 15
#define MAX_SIDE (2 * MAX_H + 1)
#define REJECT UINT32_MAX

typedef struct {
    uint64_t *keys;
    uint32_t *values; /* zero means empty; stored state numbers are index+1 */
    size_t capacity;
    size_t mask;
    int keyless;
    int maximum_load_percent;
} HashTable;

static void die(const char *message) {
    fprintf(stderr, "upper_graph_builder: %s\n", message);
    exit(2);
}

static void die_errno(const char *message) {
    fprintf(stderr, "upper_graph_builder: %s: %s\n", message, strerror(errno));
    exit(2);
}

static int host_is_little_endian(void) {
    const uint16_t value = UINT16_C(1);
    return *((const uint8_t *)&value) == UINT8_C(1);
}

static uint32_t little_endian_u32(uint32_t value) {
    if (host_is_little_endian()) return value;
    return ((value & UINT32_C(0x000000ff)) << 24) |
           ((value & UINT32_C(0x0000ff00)) << 8) |
           ((value & UINT32_C(0x00ff0000)) >> 8) |
           ((value & UINT32_C(0xff000000)) >> 24);
}

static uint64_t little_endian_u64(uint64_t value) {
    if (host_is_little_endian()) return value;
    return ((value & UINT64_C(0x00000000000000ff)) << 56) |
           ((value & UINT64_C(0x000000000000ff00)) << 40) |
           ((value & UINT64_C(0x0000000000ff0000)) << 24) |
           ((value & UINT64_C(0x00000000ff000000)) << 8) |
           ((value & UINT64_C(0x000000ff00000000)) >> 8) |
           ((value & UINT64_C(0x0000ff0000000000)) >> 24) |
           ((value & UINT64_C(0x00ff000000000000)) >> 40) |
           ((value & UINT64_C(0xff00000000000000)) >> 56);
}

static uint64_t mix64(uint64_t x) {
    x ^= x >> 30;
    x *= UINT64_C(0xbf58476d1ce4e5b9);
    x ^= x >> 27;
    x *= UINT64_C(0x94d049bb133111eb);
    x ^= x >> 31;
    return x;
}

static size_t next_power_of_two(size_t value) {
    size_t result = 1;
    while (result < value) {
        if (result > SIZE_MAX / 2) die("hash capacity overflow");
        result <<= 1;
    }
    return result;
}

static HashTable make_hash(size_t expected_states, int keyless) {
    HashTable table;
    table.keyless = keyless;
    table.maximum_load_percent = keyless ? 84 : 50;
    if (expected_states > (SIZE_MAX - 83) / 100) die("hash sizing overflow");
    size_t desired_capacity =
        (expected_states * 100 + (size_t)table.maximum_load_percent - 1) /
        (size_t)table.maximum_load_percent;
    table.capacity = next_power_of_two(desired_capacity);
    table.mask = table.capacity - 1;
    table.keys = keyless ? NULL : calloc(table.capacity, sizeof(uint64_t));
    table.values = calloc(table.capacity, sizeof(uint32_t));
    if ((!keyless && !table.keys) || !table.values) die_errno("cannot allocate hash table");
    return table;
}

static uint32_t find_state(const HashTable *table, const uint64_t *states, uint64_t key) {
    size_t slot = (size_t)mix64(key) & table->mask;
    while (table->values[slot] != 0) {
        uint32_t index = table->values[slot] - 1;
        if ((table->keyless ? states[index] : table->keys[slot]) == key) return index;
        slot = (slot + 1) & table->mask;
    }
    return REJECT;
}

static void insert_state(HashTable *table, uint64_t key, uint32_t index) {
    size_t slot = (size_t)mix64(key) & table->mask;
    while (table->values[slot] != 0) {
        if (!table->keyless && table->keys[slot] == key)
            die("duplicate state insertion");
        slot = (slot + 1) & table->mask;
    }
    if (!table->keyless) table->keys[slot] = key;
    table->values[slot] = index + 1;
}

static uint64_t pack_state(uint32_t x, uint32_t y, uint32_t dx, uint32_t dy, int h) {
    return (uint64_t)x | ((uint64_t)y << h) | ((uint64_t)dx << (2 * h)) |
           ((uint64_t)dy << (3 * h));
}

static void unpack_state(uint64_t state, int h, uint32_t *x, uint32_t *y,
                         uint32_t *dx, uint32_t *dy) {
    uint64_t mask = (UINT64_C(1) << h) - 1;
    *x = (uint32_t)(state & mask);
    *y = (uint32_t)((state >> h) & mask);
    *dx = (uint32_t)((state >> (2 * h)) & mask);
    *dy = (uint32_t)((state >> (3 * h)) & mask);
}

static uint32_t suffix_bits(const uint8_t *bits, int length, int h) {
    uint32_t value = 0;
    for (int i = length - h + 1; i <= length; ++i) value = (value << 1) | bits[i];
    return value;
}

static uint32_t encode_vertical(int16_t table[MAX_SIDE][MAX_SIDE], int i, int j, int h) {
    uint32_t value = 0;
    for (int ii = i - h + 1; ii <= i; ++ii) {
        int difference = table[ii][j] - table[ii - 1][j];
        if (difference < 0 || difference > 1) die("invalid vertical difference");
        value = (value << 1) | (uint32_t)difference;
    }
    return value;
}

static uint32_t encode_horizontal(int16_t table[MAX_SIDE][MAX_SIDE], int i, int j, int h) {
    uint32_t value = 0;
    for (int jj = j - h + 1; jj <= j; ++jj) {
        int difference = table[i][jj] - table[i][jj - 1];
        if (difference < 0 || difference > 1) die("invalid horizontal difference");
        value = (value << 1) | (uint32_t)difference;
    }
    return value;
}

/* Direct integer transcription of Lueker 2009 Figure 7. */
static int transition(uint64_t packed, int character, int padding, int h,
                      uint64_t *result) {
    uint32_t x, y, dx, dy;
    uint8_t top[MAX_SIDE] = {0};
    uint8_t bottom[MAX_SIDE] = {0};
    int16_t lcs[MAX_SIDE][MAX_SIDE];
    memset(lcs, 0, sizeof(lcs));
    unpack_state(packed, h, &x, &y, &dx, &dy);

    uint32_t work = x;
    for (int i = h; i >= 1; --i) {
        top[i] = (uint8_t)(work & 1U);
        work >>= 1;
    }
    work = y;
    for (int j = h; j >= 1; --j) {
        bottom[j] = (uint8_t)(work & 1U);
        work >>= 1;
    }

    lcs[h][h] = (int16_t)h;
    work = dx;
    for (int i = h; i >= 1; --i) {
        lcs[i - 1][h] = (int16_t)(lcs[i][h] - (int16_t)(work & 1U));
        work >>= 1;
    }
    work = dy;
    for (int j = h; j >= 1; --j) {
        lcs[h][j - 1] = (int16_t)(lcs[h][j] - (int16_t)(work & 1U));
        work >>= 1;
    }

    int top_len = h;
    int bottom_len = h;
    int opposite = 1 - character;
    if (padding > 0) {
        for (int count = 0; count < padding; ++count) top[++top_len] = (uint8_t)opposite;
    } else if (padding < 0) {
        for (int count = 0; count < -padding; ++count) bottom[++bottom_len] = (uint8_t)opposite;
    }
    top[++top_len] = (uint8_t)character;
    bottom[++bottom_len] = (uint8_t)character;

    for (int j = h + 1; j <= bottom_len; ++j) lcs[0][j] = lcs[0][j - 1];
    for (int i = h + 1; i <= top_len; ++i) lcs[i][0] = lcs[i - 1][0];
    for (int i = 1; i <= top_len; ++i) {
        for (int j = 1; j <= bottom_len; ++j) {
            if (i <= h && j <= h) continue;
            if (top[i] == bottom[j]) {
                lcs[i][j] = (int16_t)(lcs[i - 1][j - 1] + 1);
            } else {
                lcs[i][j] = lcs[i - 1][j] > lcs[i][j - 1] ? lcs[i - 1][j] : lcs[i][j - 1];
            }
        }
    }

    int i = top_len;
    int j = bottom_len;
    int matches = 0;
    while (i >= h && j >= h) {
        if (lcs[i][j] == lcs[i - 1][j]) {
            --i;
        } else if (lcs[i][j] == lcs[i][j - 1]) {
            --j;
        } else if (lcs[i][j] == lcs[i - 1][j - 1] + 1) {
            --i;
            --j;
            ++matches;
        } else {
            die("inconsistent LCS table during backtrack");
        }
        if (i == h && j == h) {
            if (matches != 1) die("accepted transition consumed wrong number of matches");
            uint32_t new_x = suffix_bits(top, top_len, h);
            uint32_t new_y = suffix_bits(bottom, bottom_len, h);
            uint32_t new_dx = encode_vertical(lcs, top_len, bottom_len, h);
            uint32_t new_dy = encode_horizontal(lcs, top_len, bottom_len, h);
            uint32_t mask = (UINT32_C(1) << h) - 1;
            if (new_x >= (UINT32_C(1) << (h - 1))) {
                new_x = mask - new_x;
                new_y = mask - new_y;
            }
            *result = pack_state(new_x, new_y, new_dx, new_dy, h);
            return 1;
        }
    }
    return 0;
}

static double elapsed_seconds(struct timespec start) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (double)(now.tv_sec - start.tv_sec) + 1e-9 * (double)(now.tv_nsec - start.tv_nsec);
}

int main(int argc, char **argv) {
    if (argc < 5 || argc > 7) {
        fprintf(stderr, "usage: %s HISTORY EXPECTED_STATES TRANSITIONS_OUT STATES_OUT [MAX_PROCESSED] [keyless]\n", argv[0]);
        return 2;
    }
    int h = atoi(argv[1]);
    if (h < 2 || h > MAX_H) die("history must lie in [2,15]");
    size_t expected = (size_t)strtoull(argv[2], NULL, 10);
    if (expected < 7 || expected >= UINT32_MAX) die("invalid expected state count");
    const char *transition_path = argv[3];
    const char *state_path = argv[4];
    size_t max_processed = argc == 6 ? (size_t)strtoull(argv[5], NULL, 10) : SIZE_MAX;
    if (argc == 7) max_processed = (size_t)strtoull(argv[5], NULL, 10);
    if (max_processed == 0) die("MAX_PROCESSED must be positive");
    int keyless = argc == 7 && strcmp(argv[6], "keyless") == 0;
    if (argc == 7 && !keyless) die("unknown builder mode (expected keyless)");
    FILE *transition_file = fopen(transition_path, "wb");
    if (!transition_file) die_errno("cannot open transition output");

    HashTable hash = make_hash(expected, keyless);
    size_t state_capacity = expected < 1024 ? 1024 : expected;
    uint64_t *states = malloc(state_capacity * sizeof(uint64_t));
    if (!states) die_errno("cannot allocate state queue");
    uint32_t mask = (UINT32_C(1) << h) - 1;
    states[0] = pack_state(0, 0, mask, mask, h);
    size_t state_count = 1;
    insert_state(&hash, states[0], 0);
    int columns = 2 * (2 * h - 1);
    uint32_t *row = malloc((size_t)columns * sizeof(uint32_t));
    if (!row) die_errno("cannot allocate transition row");
    struct timespec start;
    clock_gettime(CLOCK_MONOTONIC, &start);

    size_t processed = 0;
    for (; processed < state_count && processed < max_processed; ++processed) {
        int column = 0;
        for (int character = 0; character < 2; ++character) {
            for (int padding = -(h - 1); padding <= h - 1; ++padding) {
                uint64_t successor;
                if (!transition(states[processed], character, padding, h, &successor)) {
                    row[column++] = little_endian_u32(REJECT);
                    continue;
                }
                uint32_t number = find_state(&hash, states, successor);
                if (number == REJECT) {
                    if (state_count >= UINT32_MAX - 1) die("too many states for uint32 indices");
                    if (state_count == state_capacity) {
                        if (hash.keyless)
                            die("keyless state queue exhausted expected-state allocation");
                        size_t new_capacity = state_capacity + state_capacity / 2 + 1024;
                        uint64_t *grown = realloc(states, new_capacity * sizeof(uint64_t));
                        if (!grown) die_errno("cannot grow state queue");
                        states = grown;
                        state_capacity = new_capacity;
                    }
                    if (state_count > SIZE_MAX / 100 ||
                        state_count * 100 >=
                            hash.capacity * (size_t)hash.maximum_load_percent)
                        die("hash table exceeded maximum load");
                    number = (uint32_t)state_count;
                    states[state_count++] = successor;
                    insert_state(&hash, successor, number);
                }
                row[column++] = little_endian_u32(number);
            }
        }
        if (column != columns) die("transition column count mismatch");
        if (fwrite(row, sizeof(uint32_t), (size_t)columns, transition_file) != (size_t)columns)
            die_errno("cannot write transition row");
        if ((processed + 1) % 100000 == 0) {
            fprintf(stderr, "processed=%zu discovered=%zu elapsed=%.3f\n",
                    processed + 1, state_count, elapsed_seconds(start));
            fflush(stderr);
        }
    }
    if (fflush(transition_file) != 0 || fclose(transition_file) != 0)
        die_errno("cannot close transition output");
    FILE *state_file = fopen(state_path, "wb");
    if (!state_file) die_errno("cannot open state output");
    const size_t state_chunk_capacity = 1U << 20;
    uint64_t *state_chunk = malloc(state_chunk_capacity * sizeof(uint64_t));
    if (!state_chunk) die_errno("cannot allocate little-endian state output buffer");
    for (size_t offset = 0; offset < state_count;) {
        size_t count = state_count - offset;
        if (count > state_chunk_capacity) count = state_chunk_capacity;
        for (size_t index = 0; index < count; ++index)
            state_chunk[index] = little_endian_u64(states[offset + index]);
        if (fwrite(state_chunk, sizeof(uint64_t), count, state_file) != count)
            die_errno("cannot write states");
        offset += count;
    }
    free(state_chunk);
    if (fflush(state_file) != 0 || fclose(state_file) != 0) die_errno("cannot close state output");
    struct rusage usage;
    if (getrusage(RUSAGE_SELF, &usage) != 0) die_errno("getrusage failed");
#ifdef __APPLE__
    uint64_t peak_rss_bytes = (uint64_t)usage.ru_maxrss;
#else
    uint64_t peak_rss_bytes = (uint64_t)usage.ru_maxrss * 1024;
#endif
    fprintf(stdout, "history=%d states=%zu processed=%zu complete=%d columns=%d keyless=%d hash_capacity=%zu seconds=%.6f peak_rss_bytes=%" PRIu64 "\n",
            h, state_count, processed, processed == state_count, columns, keyless,
            hash.capacity,
            elapsed_seconds(start), peak_rss_bytes);
    free(row);
    free(states);
    free(hash.keys);
    free(hash.values);
    return 0;
}
