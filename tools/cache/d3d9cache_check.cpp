// d3d9cache_check.cpp -- FusionFix's D3D9 cache reader, outside the game.
//
// Compiles the ASI's own reader (source/d3d9cache.h, unchanged) into a console
// program, so what it says about a file is exactly what the replay would log, and a
// fault-injection corpus can be run through it without launching GTA IV.
//
//   d3d9cache_check check <file> [<file> ...]   one verdict line per file, in order,
//                                               de-duplicated by content as the replay
//                                               does; then the merged key count
//   d3d9cache_check snapshot                    snapshot the FusionFix.pipelinecache.f*.bin
//                                               beside this exe into d3d9cache\, as
//                                               the ASI does at launch
//   d3d9cache_check scan                        what the replay would find in the
//                                               d3d9cache and pipelinecache folders
//                                               beside this exe
//   d3d9cache_check fxc <shader dir>            the bytecode check on every shader of an
//                                               install's .fxc files: legitimate
//                                               bytecode must never be refused
//   d3d9cache_check asi <FusionFix .asi>        the same for the shaders FusionFix
//                                               embeds as RCDATA resources
//
// Build (msvc-wine, x86 like the ASI), one command:
//   ~/.local/opt/msvc/bin/x86/cl /nologo /std:c++20 /EHsc /O2 /W3 /D_CRT_SECURE_NO_WARNINGS
//       /I <fusionfix>/source d3d9cache_check.cpp <fusionfix>/source/fxc_parse.c /Fe:d3d9cache_check.exe
// Run with wine. Exit code: 0, 1 if fxc/asi found a refused shader, 2 on bad usage.
#include <windows.h>
#include <cstdio>
#include "d3d9cache.h"

static void Print(const char* s) { printf("%s\n", s); fflush(stdout); }

static int Refused(const char* what, uint32_t stage, const uint8_t* code, uint32_t size, uint32_t& ok)
{
    if (const char* why = d3d9cache::CheckBytecode(stage, code, size))
    {
        printf("REFUSED %s (%s, %u bytes): %s\n", what, stage == pipelinekeys::kStageVS ? "vs" : "ps", size, why);
        return 1;
    }
    ok++;
    return 0;
}

static int Fxc(const wchar_t* dir)
{
    const std::string d = d3d9cache::Utf8(dir);
    fxc_db* db = fxc_load_all(d.c_str());
    if (!db) { printf("cannot parse %s: %s\n", d.c_str(), fxc_last_error()); return 2; }
    uint32_t ok = 0, bad = 0;
    for (uint32_t i = 0, n = fxc_unique_count(db); i < n; i++)
    {
        const fxc_shader* s = fxc_unique_shader(db, i);
        if (!s || !s->bytecode || !s->size) continue;
        char what[32];
        _snprintf_s(what, sizeof(what), _TRUNCATE, "unique shader %u", i);
        bad += Refused(what, s->stage == FXC_STAGE_VS ? pipelinekeys::kStageVS : pipelinekeys::kStagePS,
                       s->bytecode, s->size, ok);
    }
    printf("%s: %u .fxc shaders pass, %u refused\n", d.c_str(), ok, bad);
    fxc_free(db);
    return bad ? 1 : 0;
}

static uint32_t asiOk = 0, asiBad = 0;
static BOOL CALLBACK OnRcData(HMODULE mod, LPCWSTR type, LPWSTR name, LONG_PTR)
{
    HRSRC r = FindResourceW(mod, name, type);
    DWORD size = r ? SizeofResource(mod, r) : 0;
    HGLOBAL g = r ? LoadResource(mod, r) : nullptr;
    const uint8_t* data = g ? static_cast<const uint8_t*>(LockResource(g)) : nullptr;
    if (!data || size < 8 || (size & 3)) return TRUE;
    uint32_t ver;
    memcpy(&ver, data, 4);
    if ((ver >> 16) != 0xFFFE && (ver >> 16) != 0xFFFF) return TRUE;   // not a shader (as OnOwnRcData)
    char what[64];
    if (IS_INTRESOURCE(name)) _snprintf_s(what, sizeof(what), _TRUNCATE, "resource #%u", (unsigned)(uintptr_t)name);
    else _snprintf_s(what, sizeof(what), _TRUNCATE, "resource %s", d3d9cache::Utf8(name).c_str());
    asiBad += Refused(what, (ver >> 16) == 0xFFFE ? pipelinekeys::kStageVS : pipelinekeys::kStagePS, data, size, asiOk);
    return TRUE;
}

static int Asi(const wchar_t* path)
{
    HMODULE m = LoadLibraryExW(path, nullptr, LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_IMAGE_RESOURCE);
    if (!m) { printf("cannot load %s\n", d3d9cache::Utf8(path).c_str()); return 2; }
    EnumResourceNamesW(m, MAKEINTRESOURCEW(10) /* RT_RCDATA */, &OnRcData, 0);
    printf("%s: %u embedded shaders pass, %u refused\n", d3d9cache::Utf8(path).c_str(), asiOk, asiBad);
    FreeLibrary(m);
    return asiBad ? 1 : 0;
}

static int Check(int argc, wchar_t** argv)
{
    using namespace pipelinekeys;
    std::unordered_map<uint64_t, std::string> seen;
    std::unordered_map<uint64_t, uint32_t> declIndex;   // declaration bytes -> merged index
    std::unordered_set<uint64_t> keys;                  // merged key identities
    uint32_t accepted = 0, rejected = 0, duplicate = 0, skipped = 0;
    for (int i = 2; i < argc; i++)
    {
        std::wstring path = argv[i];
        const size_t slash = path.find_last_of(L"\\/");
        const std::string label = d3d9cache::Utf8(slash == std::wstring::npos ? path : path.substr(slash + 1));
        CacheContents c;
        d3d9cache::FileResult f = d3d9cache::LoadFile(path, label, "win32_30", seen, c);
        printf("%s: %s\n", label.c_str(), d3d9cache::Describe(f, c).c_str());
        switch (f.verdict)
        {
        case d3d9cache::Verdict::Accepted:  accepted++;  break;
        case d3d9cache::Verdict::Duplicate: duplicate++; break;
        case d3d9cache::Verdict::Skipped:   skipped++;   break;
        default:                            rejected++;  break;
        }
        if (f.verdict != d3d9cache::Verdict::Accepted) continue;

        // The replay's merge identity: declarations by their bytes, keys by every
        // field before the count.
        std::vector<uint32_t> remap(c.decls.size());
        for (size_t d = 0; d < c.decls.size(); d++)
        {
            const uint64_t h = Fnv1a(c.decls[d].data(), c.decls[d].size() * sizeof(D3DVERTEXELEMENT9));
            remap[d] = declIndex.emplace(h, (uint32_t)declIndex.size()).first->second;
        }
        size_t added = 0;
        for (KeyRecord k : c.keys)
        {
            if (k.declIndex != kDeclNone) k.declIndex = remap[k.declIndex];
            added += keys.insert(Fnv1a(&k, kKeyHashBytes)).second;
        }
        printf("  -> %zu keys new to the merged set\n", added);
    }
    printf("summary: %u accepted, %u rejected, %u duplicate, %u skipped; merged set %zu keys, %zu declarations\n",
           accepted, rejected, duplicate, skipped, keys.size(), declIndex.size());
    return 0;
}

static int Scan()
{
    d3d9cache::DropIns d = d3d9cache::FindDropIns();
    for (auto& f : d.files) printf("bin: %s\n", d3d9cache::Utf8(f).c_str());
    for (auto& f : d.other) printf("other: %s\n", d3d9cache::Utf8(f).c_str());
    printf("subdirs: %u (first '%s')\n", d.subdirs, d3d9cache::Utf8(d.firstSubdir).c_str());
    printf("foz: %u (first '%s')\n", d.foz, d3d9cache::Utf8(d.firstFoz).c_str());
    printf("bins in pipelinecache: %u (first '%s')\n", d.misplacedBins, d3d9cache::Utf8(d.firstMisplaced).c_str());
    printf("active shader dir here: %s\n", d3d9cache::ActiveShaderDir().c_str());
    return 0;
}

int wmain(int argc, wchar_t** argv)
{
    if (argc >= 3 && !wcscmp(argv[1], L"check")) return Check(argc, argv);
    if (argc == 2 && !wcscmp(argv[1], L"snapshot")) { d3d9cache::SnapshotOwnCaptures(Print); return 0; }
    if (argc == 2 && !wcscmp(argv[1], L"scan")) return Scan();
    if (argc == 3 && !wcscmp(argv[1], L"fxc")) return Fxc(argv[2]);
    if (argc == 3 && !wcscmp(argv[1], L"asi")) return Asi(argv[2]);
    fprintf(stderr, "usage: d3d9cache_check check <file>... | snapshot | scan | fxc <dir> | asi <file>\n");
    return 2;
}
