// SPDX-License-Identifier: ISC
// nextpnr Himbaechel micro-architecture for the Intel Cyclone 10 LP 10CL016 (c10lp project).  The chip database comes
// from c10lp's validated models (c10lp/nextpnr/c10lp_arch_gen.py); this file packs and checks placement.  Based on the
// nextpnr example uarch (Copyright (C) 2023 gatecat, ISC licence).

#include "himbaechel_api.h"
#include "log.h"
#include "nextpnr.h"
#include "util.h"

#include "himbaechel_helpers.h"

#define GEN_INIT_CONSTIDS
#define HIMBAECHEL_CONSTIDS "uarch/c10lp/constids.inc"
#define HIMBAECHEL_UARCH c10lp
#include "himbaechel_constids.h"

NEXTPNR_NAMESPACE_BEGIN

namespace {
struct C10lpImpl : HimbaechelAPI
{
    ~C10lpImpl() {};

    po::options_description getUArchOptions() override
    {
        po::options_description specific("Cyclone 10 LP (c10lp) options");
        return specific;
    }

    void init_database(Arch *arch) override
    {
        init_uarch_constids(arch);
        arch->load_chipdb("c10lp/chipdb-10CL016.bin");
        arch->set_speed_grade("DEFAULT");
    }

    void init(Context *ctx) override
    {
        h.init(ctx);
        HimbaechelAPI::init(ctx);
        id_en = ctx->id("EN");
        id_clrn = ctx->id("CLRN");
        id_sclr = ctx->id("SCLR");
    }

    void pack() override
    {
        // The clock comes from a GCLK_DRV cell; I/O cells (c10lp_netlist.py --io) are pinned to their pads.  A
        // register's D is its own LUT's output (the only D path).
        int lutffs = h.constrain_cell_pairs(pool<CellTypePort>{{id_LUT4, id_F}}, pool<CellTypePort>{{id_DFF, id_D}}, 1);
        log_info("Constrained %d LUT-register pairs.\n", lutffs);
    }

    bool isBelLocationValid(BelId bel, bool explain_invalid) const override
    {
        // a register shares its LE with the LUT that drives it, and no LUT drives a register in another LE
        if (ctx->getBelType(bel) != id_DFF)
            return true;
        const CellInfo *ff = ctx->getBoundBelCell(bel);
        if (!ff)
            return true;
        Loc l = ctx->getBelLocation(bel);
        const CellInfo *lut = ctx->getBoundBelCell(ctx->getBelByLocation(Loc(l.x, l.y, l.z - 1)));
        if (!lut)
            return true; // the LUT isn't placed yet (constrained placement binds the pair one cell at a time)
        const NetInfo *d = ff->getPort(id_D);
        if (!d || lut->getPort(id_F) != d)
            return false;
        // LAB-wide controls (LAB_CONTROL_MUX): every register of a LAB shares the clock enable (pair 0, slot 2; a
        // register without one would be gated too) and the sync clear (slot 2 as well, so not both in one LAB), and at
        // most one async clear net drives the LAB (slot 0; per-register enables let others run without it)
        const NetInfo *en = ff->getPort(id_en), *sclr = ff->getPort(id_sclr), *clrn = ff->getPort(id_clrn);
        for (int z = 1; z < 32; z += 2) {
            if (z == l.z)
                continue;
            const CellInfo *o = ctx->getBoundBelCell(ctx->getBelByLocation(Loc(l.x, l.y, z)));
            if (!o || o->type != id_DFF)
                continue;
            if (o->getPort(id_en) != en || o->getPort(id_sclr) != sclr)
                return false;
            const NetInfo *oc = o->getPort(id_clrn);
            if (oc && clrn && oc != clrn)
                return false;
        }
        return !(en && sclr);
    }

    IdString getBelBucketForCellType(IdString cell_type) const override { return cell_type; }
    bool isValidBelForCellType(IdString cell_type, BelId bel) const override
    {
        return ctx->getBelType(bel) == cell_type;
    }

  private:
    HimbaechelHelpers h;
    IdString id_en, id_clrn, id_sclr;
};

struct C10lpArch : HimbaechelArch
{
    C10lpArch() : HimbaechelArch("c10lp") {};
    bool match_device(const std::string &device) override { return device == "10CL016"; }
    std::unique_ptr<HimbaechelAPI> create(const std::string &device) override
    {
        return std::make_unique<C10lpImpl>();
    }
} c10lpArch;
} // namespace

NEXTPNR_NAMESPACE_END
