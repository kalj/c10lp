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
    }

    void pack() override
    {
        // The netlist (c10lp/nextpnr/c10lp_netlist.py) has no I/O cells: the clock comes from a GCLK_DRV cell and the
        // output pin is routed outside nextpnr.  A register's D is its own LUT's output (the only D path).
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
        return d && lut->getPort(id_F) == d;
    }

    IdString getBelBucketForCellType(IdString cell_type) const override { return cell_type; }
    bool isValidBelForCellType(IdString cell_type, BelId bel) const override
    {
        return ctx->getBelType(bel) == cell_type;
    }

  private:
    HimbaechelHelpers h;
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
