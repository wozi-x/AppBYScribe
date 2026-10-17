# Research and provenance

The parser is an independent implementation of observed binary structures. Public source code was consulted for format-family comparisons and semantic hypotheses. No upstream implementation is vendored in this repository. No personal recordings or screen observations are distributed.

- [djmed](https://github.com/Centurix/djmed), inspected revision `c398c087dfd64db0fd5c0f9392c15cf5b2ef76c4`: related BYS grammars and older BreathCare layouts.
- [OSCAR-SQL Yuwell loader](https://gitlab.com/CrimsonNape/OSCAR-SQL/-/blob/1817a30791e4d38c680c991e118e7b7993de7d04/oscar/SleepLib/loader_plugins/yuwell_loader.cpp), inspected revision `1817a30791e4d38c680c991e118e7b7993de7d04`: Format E provides the closest minute-record comparison. The [official OSCAR download page](https://www.sleepfiles.com/OSCAR/) links its source repository.

The related Format E device is not an automatic ET525A compatibility guarantee. Its event handling differs from the working counter-sum interpretation, and older detail loops do not account for this format's extra terminator byte. Candidate meanings must pass local structural/arithmetic checks and remain explicitly labeled until independently validated.

Evidence priority: original byte relationships, matching public layout, cross-field consistency, then exact-session vendor-screen comparison. A physiological-looking value alone never establishes a field's meaning. No exact public ET525A binary specification was obtained during this research.
