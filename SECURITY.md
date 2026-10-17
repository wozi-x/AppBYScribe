# Security and privacy

Real recordings, photos, observations and generated reports belong under the ignored `private/` directory. Git ignore rules are not encryption. Never force-add these files or publish an archive of the whole working directory.

The workflow rejects symlinks/special input entries, checks input stability, preserves byte provenance and uses a lock for library writes. It has no runtime networking. Unknown/untrusted binary content must not be executed. Large exports can consume substantial disk space.

For a suspected vulnerability, share a minimal synthetic reproducer without personal data. This local repository has no configured remote security-reporting channel; maintainers should configure one before inviting private vulnerability reports on a hosting service.
