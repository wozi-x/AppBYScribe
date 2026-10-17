# Research and provenance

Independent implementation based on observed bytes and related public format research. No upstream code or personal recordings are distributed.

- [djmed](https://github.com/Centurix/djmed), inspected revision `c398c087dfd64db0fd5c0f9392c15cf5b2ef76c4`: related BYS grammars and older BreathCare layouts.
- [OSCAR-SQL Yuwell loader](https://gitlab.com/CrimsonNape/OSCAR-SQL/-/blob/1817a30791e4d38c680c991e118e7b7993de7d04/oscar/SleepLib/loader_plugins/yuwell_loader.cpp), inspected revision `1817a30791e4d38c680c991e118e7b7993de7d04`: Format E provides the closest minute-record comparison. The [official OSCAR download page](https://www.sleepfiles.com/OSCAR/) links its source repository.

Format E is a comparison, not an ET525A compatibility guarantee. Its event handling differs from our candidate counter sums; older detail loops also omit this format's extra terminator byte. Mappings remain qualified until independently validated.

Evidence: original byte relationships, public layouts, cross-field checks and exact-session screen comparisons. Plausible values alone do not establish meaning. No complete official ET525A binary specification was obtained; see [FORMAT.md](FORMAT.md) for supported layouts and uncertainties.
