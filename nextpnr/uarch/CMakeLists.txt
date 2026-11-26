# c10lp uarch: the chip database is generated outside the nextpnr build (c10lp/nextpnr/build.sh), from c10lp's models
set(SOURCES
    constids.inc
    c10lp.cc
)

add_nextpnr_himbaechel_microarchitecture(${uarch}
    CORE_SOURCES ${SOURCES}
)
