/* Dump every unique shader in RAGE's .fxc database as "stage hash size".
 *
 * WHY: the shipped baseline replays pipeline keys harvested from ACTUAL PLAY, so it
 * can only cover shaders we happened to draw. The .fxc database is the complete set
 * the game could ever use. Diffing the two sizes the coverage gap -- i.e. how much a
 * playthrough-independent approach could possibly add -- before any of it is built.
 *
 * Builds natively: fxc_parse.c is pure C99 byte parsing with no D3D dependency.
 *   cc -O2 -o fxc_hashes fxc_hashes.c <fusionfix>/source/fxc_parse.c -I<fusionfix>/source
 */
#include <stdio.h>
#include <stdint.h>
#include "fxc_parse.h"

static uint64_t fnv1a(const void *p, size_t n)
{
    const unsigned char *b = (const unsigned char *)p;
    uint64_t h = 1469598103934665603ULL;
    for (size_t i = 0; i < n; i++) { h ^= b[i]; h *= 1099511628211ULL; }
    return h;
}

int main(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "usage: fxc_hashes <shader dir>\n"); return 2; }
    fxc_db *db = fxc_load_all(argv[1]);
    if (!db) { fprintf(stderr, "load failed: %s\n", fxc_last_error()); return 1; }

    fxc_stats st;
    fxc_get_stats(db, &st);
    fprintf(stderr, "effects=%u techniques=%u passes=%u unique_vs=%u unique_ps=%u errors=%u\n",
            fxc_effect_count(db), st.technique_count, st.pass_count,
            st.unique_vs, st.unique_ps, st.parse_errors);

    uint32_t n = fxc_unique_count(db);
    for (uint32_t i = 0; i < n; i++)
    {
        const fxc_shader *s = fxc_unique_shader(db, i);
        if (!s || !s->bytecode || !s->size) continue;
        printf("%s %016llx %u\n",
               s->stage == FXC_STAGE_VS ? "vs" : "ps",
               (unsigned long long)fnv1a(s->bytecode, s->size),
               (unsigned)s->size);
    }
    fxc_free(db);
    return 0;
}
