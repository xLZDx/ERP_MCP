# Source-to-R2 commit map

Release 2 was extracted from the Release 1 repository with `git filter-branch` (see `EXTRACTION_NOTE.md`). Every commit hash changed. GPT-PM approvals and the decision log cite the ORIGINAL (source) hashes; those hashes do not resolve in this repository. Use this table to translate them. The match was made by author timestamp and subject (unique for every row), and verified by comparing the git tree hashes of `src/business_ai_gateway/phase2` and `tests/phase2` in both repositories ("equal" = byte-identical content for the Phase 2 code and tests).

Commits made in the source repository after the extraction clone (source head `9810c29`) were carried over as file content, not as history, so they have no R2 hash.

| Gate / sprint | Source hash (original, full) | R2 hash (rewritten, full) | Phase 2 src and tests trees |
| --- | --- | --- | --- |
| G1 push approval | `45a7b1a2a519acc5392f4d57f2191df04a117fc1` | `4e7db80c6c924a5e20f8017a6cbd936e71eede05` | equal |
| G1 exit evidence | `df92cc828b5d81d40dca839393fa28bcea0de08c` | `6ac0d0d3702ab034ea07dd946903ab5f199a92c5` | equal |
| S1-S4 | `5000043339e6573b7ebf7644f2cd3e2f73871c06` | `c9de6836b366a48796151db75d5538c22acdfa28` | equal |
| S4b | `a2219b0e902c250f26a94df791a815eae16313ff` | `24b205bc8e3bc2060a97b24dde234bbbe9a9fdc1` | equal |
| S4b merge of origin main | `6f80219d5bcd0b91a00de67a70e4a63efca5f9d9` | `0d3b482e9c623d3e65306b3b84b42a929d3ea9b5` | equal |
| S5 | `af9f287b76c3cc6c83bd96241ac269f86660e801` | `23e1ac4f43188a5d698c385add6e427f709810c2` | equal |
| S6 (per the S6 report) | `c194760a705ce686d8f944ba61b60ee128b00951` | `198eabb1a73714eb4d67b9fcca2401428d90b71f` | equal |
| S6b REJECT head | `09536a3e261096a3ee399269aa98d0f72e00711e` | `12a3527c7872cb2961b770b8622196cd57aa5f9e` | equal |
| S6b | `b5ae365c662294c163bcfa98577d8ed65630eb15` | `6016f80a1ce7eb3d52d2d0a686e81026fc74e8fa` | equal |
| S7/S8 first REJECT head | `e5761eb89a7ecdbd6a8cecb1b0c842c651b6eb21` | `42bb74fa1fae626e4d2f49daae2e1ea6031f8e62` | equal |
| S7 and S8 | `fa4852d85bff6150ca7629649f1cfa7fb9a973c3` | `7e483ca51f5ba50dba63cea0bf615b07699f307f` | equal |
| S9 round 1 REJECT head | `292a62dfc88de162ca89fc37fe722a47e733414d` | `ef8731028a661d816b5fbd472b532d65112a892c` | equal |
| S9 round 2 REJECT head | `23a055f875ed20f12d65b6b47890b0f1ea3b951d` | `0a32150768408fbe0c8d96d8517293e3c35ea8cb` | equal |
| S9 round 3 REJECT head | `92cc3d9bee731566e1a4c29a6e1479b491b2e3fc` | `55cc687c6ddcb317896de0239f38cddeaa2291ff` | equal |
| S9 | `6ee27f1456f9533c2d622677265cbb87ab188cfa` | `0d4eef11c6917441d41a34b60551563c40d9e111` | equal |
| S10 | `88753c207602927c0a72ce2805534b4929e4879f` | `71bd8a393c2a3c762b444d05160fe06b004c6025` | equal |

An approval recorded against a source hash applies to the content of the matching R2 commit only when the last column says "equal". A new approval is required for any other R2 head, including the head named in the release decision.
