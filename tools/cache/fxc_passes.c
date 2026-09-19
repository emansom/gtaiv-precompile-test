/* Dump every technique/pass in RAGE's .fxc database with its shader pair and the
 * render states the pass programs.
 *
 * WHY: capture+replay only covers shaders we happened to draw (measured: 498 of
 * 1734, and 6.9x more captured keys reached the SAME 498). The .fxc database holds
 * every pass the game can run. If a pass's declared state agrees with the state we
 * actually observed for the same shader pair, then passes we never drew can be
 * turned into real pipeline keys without a playthrough. This dumps the left-hand
 * side of that comparison; fxcsynth.py does the comparison against captured keys.
 *
 * Output, one line per pass, tab-separated:
 *   effect  technique  pass_index  vs_hash  ps_hash  type:value,type:value,...
 * ps_hash is 0 when the pass declares no pixel shader.
 *
 *   cc -O2 -o fxc_passes fxc_passes.c <fusionfix>/source/fxc_parse.c -I<fusionfix>/source
 */
#include <stdio.h>
#include <stdint.h>
#include "fxc_parse.h"

int main(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "usage: fxc_passes <shader dir>\n"); return 2; }
    fxc_db *db = fxc_load_all(argv[1]);
    if (!db) { fprintf(stderr, "load failed: %s\n", fxc_last_error()); return 1; }

    uint32_t ne = fxc_effect_count(db);
    for (uint32_t e = 0; e < ne; e++)
    {
        const fxc_effect *ef = fxc_get_effect(db, e);
        if (!ef) continue;
        for (uint32_t t = 0; t < ef->technique_count; t++)
        {
            const fxc_technique *tech = &ef->techniques[t];
            for (uint32_t p = 0; p < tech->pass_count; p++)
            {
                const fxc_pass *pass = &tech->passes[p];
                const fxc_shader *vs = (pass->vs_unique != FXC_NO_SHADER)
                                     ? fxc_unique_shader(db, pass->vs_unique) : NULL;
                const fxc_shader *ps = (pass->ps_unique != FXC_NO_SHADER)
                                     ? fxc_unique_shader(db, pass->ps_unique) : NULL;

                printf("%s\t%s\t%u\t%016llx\t%016llx\t",
                       ef->name ? ef->name : "?",
                       tech->name ? tech->name : "?",
                       p,
                       vs ? (unsigned long long)vs->hash : 0ULL,
                       ps ? (unsigned long long)ps->hash : 0ULL);

                for (uint32_t v = 0; v < pass->value_count; v++)
                    printf("%s%u:%u", v ? "," : "",
                           pass->values[v].type, pass->values[v].value);
                printf("\n");
            }
        }
    }
    fxc_free(db);
    return 0;
}
