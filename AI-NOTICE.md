# ⚠️ LLM SLOP — personal RE scratch branch, NOT upstream-ready

Every commit on this branch is **LLM-generated** experimental reverse-
engineering work ("LLM SLOP"). It is a personal scratch branch, was never
submitted anywhere, and none of it is clean-room or upstream-ready.

Commits whose subject says **`LLM SLOP TAINTED (RE-derived, DO NOT UPSTREAM)`**
are additionally derived from disassembling Apple's macOS drivers
(AppleT6040TypeCPhy, AppleANS3CGv2Controller, AppleT6040PCIe). Those MUST NOT
be upstreamed or used as a clean-room reference under any circumstances.

The original kernel-style commit messages are preserved verbatim in each
commit body, so any non-tainted work can be cleanly renamed/rewritten if it
is ever re-derived properly for submission.