#include <stddef.h>
#include <stdint.h>

#if !defined(__SIZEOF_INT128__) || __SIZEOF_INT128__ != 16
#error "upper_exact.c requires a compiler with unsigned __int128"
#endif

/*
 * Exact fixed-point normalization for the power-iteration engine.
 *
 * raw[i] and raw_max are uint64, while witness_scale is a positive uint32.
 * Their product can require 96 bits, so a uint64 implementation would not be
 * correct over the engine's declared input domain.  Clang and GCC provide the
 * 128-bit integer used here on supported macOS and Linux targets.
 */
int normalize_exact_u64_to_u32(const uint64_t *raw, uint32_t *output,
                               size_t size, uint64_t witness_scale,
                               uint64_t raw_max) {
    if (raw == NULL || output == NULL || witness_scale == 0 ||
        witness_scale > UINT32_MAX || raw_max == 0) {
        return 1;
    }
    for (size_t index = 0; index < size; ++index) {
        if (raw[index] > raw_max) return 2;
        unsigned __int128 product =
            (unsigned __int128)raw[index] * (unsigned __int128)witness_scale;
        uint64_t value = (uint64_t)(product / raw_max);
        if (value < 1) value = 1;
        if (value > witness_scale) value = witness_scale;
        output[index] = (uint32_t)value;
    }
    return 0;
}
