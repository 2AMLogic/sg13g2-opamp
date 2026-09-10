v {xschem version=3.4.8RC file_version=1.3
* opamp_core -- two-stage Miller-compensated op-amp core (issue #9), per
* spec/decision-records/0001-topology-and-cl.md (DR-1): NMOS input pair,
* PMOS current-mirror load, NMOS tail current source, single-ended Class-A
* common-source PMOS output gain device loaded by an NMOS current sink,
* non-cascoded, Cc Miller compensation into CL = 2 pF [DR-1]. CMOS only,
* per CLAUDE.md (sg13_lv_nmos / sg13_lv_pmos, cap_cmim for Cc -- no HBT
* device anywhere in this schematic).
*
* Full gm/ID sizing derivation for every device below, citing literal rows
* of sim/gm-id-characterization/records/20260909-063633-b402592.csv, is in
* design/opamp_sizing.md -- read that first; this header is a short
* pointer, not a re-derivation.
*
* --------------------------------------------------------------- topology
* Stage 1 (differential-to-single-ended transconductance stage):
*   M1, M2   sg13_lv_nmos input pair. Sources tied together at "tail".
*            M1 gate = inn (inverting), M2 gate = inp (non-inverting) --
*            see "polarity" below. M1 drain = d1 (diode/mirror-reference
*            side), M2 drain = d2 (mirror-output side, drives stage 2).
*   M3, M4   sg13_lv_pmos current-mirror load, sources tied to vdd. M3 is
*            diode-connected (gate = drain = d1); M4 mirrors (gate = d1,
*            drain = d2).
*   M5       sg13_lv_nmos tail current source. Drain = tail, gate = ibias,
*            source = vss.
*   Mbias    sg13_lv_nmos diode-connected bias reference (gate = drain =
*            ibias, source = vss), unit-matched to M5 (same W/L) so the
*            external ibias pin's current mirrors 1:1 into the tail. Also
*            the mirror reference for M7 below (same L, different W ratio)
*            -- see opamp_sizing.md "Bias scope" for why this design
*            deliberately uses ONE diode-connected bias device rather than
*            a second bias branch at a different length.
*
* Stage 2 (second gain stage + compensation):
*   M6       sg13_lv_pmos output gain device, source = vdd, gate = d2
*            (stage-1 output), drain = out.
*   M7       sg13_lv_nmos output current sink, drain = out, gate = ibias
*            (mirrors Mbias, same L, scaled W), source = vss.
*   Cc       cap_cmim Miller compensation cap, from out to d2 (across the
*            M6 common-source stage). No nulling Rz in this first pass --
*            see opamp_sizing.md "Rz" section for why, and the candidate
*            value if a future pass needs one.
*
* -------------------------------------------------------------- polarity
* Small-signal path from inp [M2 gate] to out: raising inp steers relatively
* less of the shared tail current through M2's branch (d2); the M3/M4
* mirror (fixed by the M1/d1 diode side) then pushes d2 UP as M4 keeps
* sourcing its mirrored current into a branch drawing less of it away --
* one inversion (inp low-to-high maps to d2 rising is itself the composite
* result of the differential pair + mirror acting as a single inverting-at-
* d1/non-inverting-at-d2 transconductance stage, worked through in full in
* design/opamp_sizing.md). d2 rising then lowers M6's Vsg (PMOS, source at
* vdd), so M6 sources less current into "out", and the fixed M7 sink pulls
* "out" DOWN -- wait, restated for the sign actually implemented here: this
* schematic wires M1 (the diode/d1 side of the input pair) to inn and M2
* (the mirror-output/d2 side) to inp, which is the assignment
* opamp_sizing.md's own signed derivation concludes gives a NON-inverting
* inp and INVERTING inn (out rises when inp rises, falls when inn rises).
* Read that file's polarity derivation for the full signed argument; this
* comment names the conclusion the wiring below implements.
*
* Pins: vdd, vss, inn, inp, out, ibias.
}
G {}
K {}
V {}
S {}
E {}
C {sg13g2_pr/sg13_lv_nmos.sym} -800 400 0 0 {name=M1 model=sg13_lv_nmos w=3.2u l=0.13u ng=1 m=1}
N -820 400 -840 400 {}
C {lab_pin.sym} -840 400 0 0 {name=l1 lab=inn}
N -780 370 -760 350 {}
C {lab_pin.sym} -760 350 0 0 {name=l2 lab=d1}
N -780 400 -760 400 {}
C {lab_pin.sym} -760 400 0 0 {name=l3 lab=vss}
N -780 430 -760 450 {}
C {lab_pin.sym} -760 450 0 0 {name=l4 lab=tail}

C {sg13g2_pr/sg13_lv_nmos.sym} -400 400 0 0 {name=M2 model=sg13_lv_nmos w=3.2u l=0.13u ng=1 m=1}
N -420 400 -440 400 {}
C {lab_pin.sym} -440 400 0 0 {name=l5 lab=inp}
N -380 370 -360 350 {}
C {lab_pin.sym} -360 350 0 0 {name=l6 lab=d2}
N -380 400 -360 400 {}
C {lab_pin.sym} -360 400 0 0 {name=l7 lab=vss}
N -380 430 -360 450 {}
C {lab_pin.sym} -360 450 0 0 {name=l8 lab=tail}

C {sg13g2_pr/sg13_lv_pmos.sym} -800 0 0 0 {name=M3 model=sg13_lv_pmos w=1.04u l=0.52u ng=1 m=1}
N -820 0 -840 0 {}
C {lab_pin.sym} -840 0 0 0 {name=l9 lab=d1}
N -780 30 -760 50 {}
C {lab_pin.sym} -760 50 0 0 {name=l10 lab=d1}
N -780 -30 -760 -50 {}
C {lab_pin.sym} -760 -50 0 0 {name=l11 lab=vdd}
N -780 0 -760 0 {}
C {lab_pin.sym} -760 0 0 0 {name=l12 lab=vdd}

C {sg13g2_pr/sg13_lv_pmos.sym} -400 0 0 0 {name=M4 model=sg13_lv_pmos w=1.04u l=0.52u ng=1 m=1}
N -420 0 -440 0 {}
C {lab_pin.sym} -440 0 0 0 {name=l13 lab=d1}
N -380 30 -360 50 {}
C {lab_pin.sym} -360 50 0 0 {name=l14 lab=d2}
N -380 -30 -360 -50 {}
C {lab_pin.sym} -360 -50 0 0 {name=l15 lab=vdd}
N -380 0 -360 0 {}
C {lab_pin.sym} -360 0 0 0 {name=l16 lab=vdd}

C {sg13g2_pr/sg13_lv_nmos.sym} -800 800 0 0 {name=M5 model=sg13_lv_nmos w=2.2u l=0.52u ng=1 m=1}
N -820 800 -840 800 {}
C {lab_pin.sym} -840 800 0 0 {name=l17 lab=ibias}
N -780 770 -760 750 {}
C {lab_pin.sym} -760 750 0 0 {name=l18 lab=tail}
N -780 800 -760 800 {}
C {lab_pin.sym} -760 800 0 0 {name=l19 lab=vss}
N -780 830 -760 850 {}
C {lab_pin.sym} -760 850 0 0 {name=l20 lab=vss}

C {sg13g2_pr/sg13_lv_nmos.sym} -400 800 0 0 {name=Mbias model=sg13_lv_nmos w=2.2u l=0.52u ng=1 m=1}
N -420 800 -440 800 {}
C {lab_pin.sym} -440 800 0 0 {name=l21 lab=ibias}
N -380 770 -360 750 {}
C {lab_pin.sym} -360 750 0 0 {name=l22 lab=ibias}
N -380 800 -360 800 {}
C {lab_pin.sym} -360 800 0 0 {name=l23 lab=vss}
N -380 830 -360 850 {}
C {lab_pin.sym} -360 850 0 0 {name=l24 lab=vss}

C {sg13g2_pr/sg13_lv_pmos.sym} 400 0 0 0 {name=M6 model=sg13_lv_pmos w=33u l=1.04u ng=1 m=1}
N 380 0 360 0 {}
C {lab_pin.sym} 360 0 0 0 {name=l25 lab=d2}
N 420 30 440 50 {}
C {lab_pin.sym} 440 50 0 0 {name=l26 lab=out}
N 420 -30 440 -50 {}
C {lab_pin.sym} 440 -50 0 0 {name=l27 lab=vdd}
N 420 0 440 0 {}
C {lab_pin.sym} 440 0 0 0 {name=l28 lab=vdd}

C {sg13g2_pr/sg13_lv_nmos.sym} 400 400 0 0 {name=M7 model=sg13_lv_nmos w=11.9u l=0.52u ng=1 m=1}
N 380 400 360 400 {}
C {lab_pin.sym} 360 400 0 0 {name=l29 lab=ibias}
N 420 370 440 350 {}
C {lab_pin.sym} 440 350 0 0 {name=l30 lab=out}
N 420 430 440 450 {}
C {lab_pin.sym} 440 450 0 0 {name=l31 lab=vss}
N 420 400 440 400 {}
C {lab_pin.sym} 440 400 0 0 {name=l32 lab=vss}

C {sg13g2_pr/cap_cmim.sym} 900 200 0 0 {name=Cc model=cap_cmim w=25.7u l=25.7u m=1}
N 900 170 900 150 {}
C {lab_pin.sym} 900 150 0 0 {name=l33 lab=out}
N 900 230 900 250 {}
C {lab_pin.sym} 900 250 0 0 {name=l34 lab=d2}

C {iopin.sym} -1100 -200 0 0 {name=p1 lab=vdd}
C {iopin.sym} -1100 1000 0 0 {name=p2 lab=vss}
C {iopin.sym} -1100 400 0 0 {name=p3 lab=inn}
C {iopin.sym} -1100 600 0 0 {name=p4 lab=inp}
C {iopin.sym} 1300 200 0 0 {name=p5 lab=out}
C {iopin.sym} -1100 800 0 0 {name=p6 lab=ibias}
