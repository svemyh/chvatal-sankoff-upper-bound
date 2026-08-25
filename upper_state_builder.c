/* Restartable keyless state discovery for the matrix-free upper-bound run.
 *
 * Reuse the already calibrated transition implementation from the stored-graph
 * builder, but persist only the canonical state queue and its uint32 keyless
 * lookup table.  A Python driver provides copy-on-write transactional files.
 */
#define main upper_graph_builder_unused_main
#include "upper_graph_builder.c"
#undef main

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

static uint64_t parse_u64(const char *text, const char *name) {
    char *end = NULL;
    errno = 0;
    uint64_t value = strtoull(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0') {
        fprintf(stderr, "upper_state_builder: invalid %s\n", name);
        exit(2);
    }
    return value;
}

static void require_regular_size(int fd, uint64_t expected, const char *name) {
    struct stat status;
    if (fstat(fd, &status) != 0) die_errno("cannot stat persistent file");
    if ((uint64_t)status.st_size != expected) {
        fprintf(stderr,
                "upper_state_builder: %s size mismatch: got=%" PRIu64
                " expected=%" PRIu64 "\n",
                name, (uint64_t)status.st_size, expected);
        exit(2);
    }
}

int main(int argc, char **argv) {
    if (argc != 9) {
        fprintf(stderr,
                "usage: %s HISTORY STATE_LIMIT HASH_CAPACITY STATES VALUES "
                "PROCESSED STATE_COUNT STOP_PROCESSED\n",
                argv[0]);
        return 2;
    }
    int h = atoi(argv[1]);
    if (h < 2 || h > MAX_H) die("history must lie in [2,15]");
    uint64_t state_limit_u64 = parse_u64(argv[2], "STATE_LIMIT");
    uint64_t hash_capacity_u64 = parse_u64(argv[3], "HASH_CAPACITY");
    uint64_t processed_u64 = parse_u64(argv[6], "PROCESSED");
    uint64_t state_count_u64 = parse_u64(argv[7], "STATE_COUNT");
    uint64_t stop_processed_u64 = parse_u64(argv[8], "STOP_PROCESSED");
    if (state_limit_u64 == 0 || state_limit_u64 >= UINT32_MAX ||
        hash_capacity_u64 == 0 ||
        (hash_capacity_u64 & (hash_capacity_u64 - 1)) != 0 ||
        hash_capacity_u64 > SIZE_MAX / sizeof(uint32_t) ||
        state_limit_u64 > SIZE_MAX / sizeof(uint64_t) ||
        processed_u64 > state_count_u64 || state_count_u64 > state_limit_u64 ||
        stop_processed_u64 < processed_u64) {
        die("invalid persistent state-builder dimensions");
    }
    size_t state_limit = (size_t)state_limit_u64;
    size_t hash_capacity = (size_t)hash_capacity_u64;
    size_t processed = (size_t)processed_u64;
    size_t state_count = (size_t)state_count_u64;
    size_t stop_processed = (size_t)stop_processed_u64;
    if (state_count > SIZE_MAX / 100 ||
        state_count * 100 >= hash_capacity * 84)
        die("starting state count exceeds the 84% keyless load limit");

    int state_fd = open(argv[4], O_RDWR);
    if (state_fd < 0) die_errno("cannot open persistent state queue");
    int values_fd = open(argv[5], O_RDWR);
    if (values_fd < 0) die_errno("cannot open persistent keyless table");
    require_regular_size(state_fd, state_count * sizeof(uint64_t), "state queue");
    require_regular_size(values_fd, hash_capacity * sizeof(uint32_t), "keyless table");
    if (ftruncate(state_fd, (off_t)(state_limit * sizeof(uint64_t))) != 0)
        die_errno("cannot expand persistent state queue");

    uint64_t *states = mmap(NULL, state_limit * sizeof(uint64_t),
                            PROT_READ | PROT_WRITE, MAP_SHARED, state_fd, 0);
    uint32_t *values = mmap(NULL, hash_capacity * sizeof(uint32_t),
                            PROT_READ | PROT_WRITE, MAP_SHARED, values_fd, 0);
    if (states == MAP_FAILED || values == MAP_FAILED)
        die_errno("cannot map persistent state-builder files");
    HashTable hash = {
        .keys = NULL,
        .values = values,
        .capacity = hash_capacity,
        .mask = hash_capacity - 1,
        .keyless = 1,
        .maximum_load_percent = 84,
    };
    uint32_t mask = (UINT32_C(1) << h) - 1;
    uint64_t seed = pack_state(0, 0, mask, mask, h);
    if (state_count == 0) {
        if (processed != 0) die("empty queue has nonzero processed count");
        states[0] = seed;
        state_count = 1;
        insert_state(&hash, seed, 0);
    } else if (states[0] != seed || find_state(&hash, states, seed) != 0) {
        die("persistent state-builder seed authentication failed");
    }

    struct timespec start;
    clock_gettime(CLOCK_MONOTONIC, &start);
    const char *wall = "none";
    int wall_hit = 0;
    for (; processed < state_count && processed < stop_processed; ++processed) {
        for (int character = 0; character < 2 && !wall_hit; ++character) {
            for (int padding = -(h - 1); padding <= h - 1; ++padding) {
                uint64_t successor;
                if (!transition(states[processed], character, padding, h, &successor))
                    continue;
                uint32_t number = find_state(&hash, states, successor);
                if (number == REJECT) {
                    if (state_count >= state_limit) {
                        wall = "state_limit";
                        wall_hit = 1;
                        break;
                    }
                    if (state_count > SIZE_MAX / 100 ||
                        state_count * 100 >= hash_capacity * 84) {
                        wall = "hash_load_84_percent";
                        wall_hit = 1;
                        break;
                    }
                    number = (uint32_t)state_count;
                    states[state_count++] = successor;
                    insert_state(&hash, successor, number);
                }
            }
        }
        if (wall_hit) break;
        if ((processed + 1) % 1000000 == 0) {
            fprintf(stderr, "processed=%zu discovered=%zu elapsed=%.3f\n",
                    processed + 1, state_count, elapsed_seconds(start));
            fflush(stderr);
        }
    }

    if (msync(states, state_count * sizeof(uint64_t), MS_SYNC) != 0 ||
        msync(values, hash_capacity * sizeof(uint32_t), MS_SYNC) != 0)
        die_errno("cannot sync persistent state-builder files");
    if (fsync(state_fd) != 0 || fsync(values_fd) != 0)
        die_errno("cannot fsync persistent state-builder files");
    if (munmap(states, state_limit * sizeof(uint64_t)) != 0 ||
        munmap(values, hash_capacity * sizeof(uint32_t)) != 0)
        die_errno("cannot unmap persistent state-builder files");
    if (ftruncate(state_fd, (off_t)(state_count * sizeof(uint64_t))) != 0 ||
        fsync(state_fd) != 0)
        die_errno("cannot seal persistent state queue");
    if (close(state_fd) != 0 || close(values_fd) != 0)
        die_errno("cannot close persistent state-builder files");

    struct rusage usage;
    if (getrusage(RUSAGE_SELF, &usage) != 0) die_errno("getrusage failed");
#ifdef __APPLE__
    uint64_t peak_rss_bytes = (uint64_t)usage.ru_maxrss;
#else
    uint64_t peak_rss_bytes = (uint64_t)usage.ru_maxrss * 1024;
#endif
    fprintf(stdout,
            "history=%d states=%zu processed=%zu complete=%d columns=%d "
            "keyless=1 hash_capacity=%zu wall=%s seconds=%.6f "
            "peak_rss_bytes=%" PRIu64 "\n",
            h, state_count, processed, !wall_hit && processed == state_count,
            2 * (2 * h - 1), hash_capacity, wall, elapsed_seconds(start),
            peak_rss_bytes);
    fflush(stdout);
    return wall_hit ? 3 : 0;
}
