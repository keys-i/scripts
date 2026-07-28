# Security audit research and limits

This document records the evidence model behind `security-audit`. The command
is a read-only coordinator: it asks native operating-system facilities and
specialist project scanners for facts, then presents possible issues for human
review. It does not replace endpoint protection, asset inventory, threat
modelling, penetration testing, vendor advisories, incident response, or a
compliance assessment.

No scanner can establish "absolute security." A clean report means only that
the selected checks found no reportable match in the files, package metadata,
catalog versions, and host interfaces they could inspect at that time.

## Identifier and prioritization model

The terms describe different things and must not be collapsed into one score:

| Signal | Meaning                                                                     | Correct use                                           | Important limit                                                                           |
| ------ | --------------------------------------------------------------------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| CVE    | A unique identifier and record for a specific published vulnerability       | Join scanner results, vendor advisories, and catalogs | A CVE ID alone does not prove that the affected product/version is installed or reachable |
| CWE    | A class of software or hardware weakness, such as improper input validation | Explain root cause and guide prevention               | It is a weakness category, not a vulnerable installed product                             |
| CVSS   | A standardized 0–10 severity assessment and vector                          | Compare technical severity and support triage         | NVD explicitly says CVSS is severity, not risk                                            |
| KEV    | CISA's catalog of CVEs with evidence of exploitation in the wild            | Raise remediation priority for an applicable finding  | It is intentionally curated, not a list of every exploited or dangerous flaw              |

The CVE Program explains that a CVE ID references one specific vulnerability
and that a published CVE Record includes affected products or versions and
public references. MITRE distinguishes a reusable CWE weakness from a concrete
vulnerability in a product. NVD describes CVSS as a qualitative severity
measure—not a risk measure—and notes that its base assessment does not include
the organization's environment. CISA describes KEV as an input to vulnerability
management prioritization based on known exploitation.

Primary sources:

- [CVE Record lifecycle and required data](https://www.cve.org/about/Process)
- [CWE definition and the weakness/vulnerability distinction](https://cwe.mitre.org/about/faq.html)
- [NVD vulnerability metrics and CVSS severity ranges](https://nvd.nist.gov/vuln-metrics/cvss)
- [CISA Known Exploited Vulnerabilities Catalog](https://www.cisa.gov/known-exploited-vulnerabilities-catalog)
- [CISA machine-readable KEV JSON](https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json)
- [CISA BOD 22-01 scope and FCEB remediation deadlines](https://www.cisa.gov/news-events/directives/bod-22-01-reducing-significant-risk-known-exploited-vulnerabilities)

### Correlation rules

`security-audit` treats a KEV match as an exact CVE-ID join. Scanner-native
identifiers such as GHSA, GO, or RUSTSEC can be correlated only when the
scanner output supplies a CVE alias. Text resemblance is not enough. A result
without a CVE remains visible but cannot be labelled as present or absent in
KEV.

KEV changes prioritization, not scanner severity: the report preserves the
scanner's CVSS score, vector, and severity, then records the exact KEV evidence
separately. Unless `--fail-on none` is selected, an applicable KEV match causes
exit 1 even below the numeric severity threshold. A catalog `dueDate` is
labelled as the CISA Federal Civilian Executive Branch due date; it is useful
context for other users, not a universal legal deadline.

Prioritization should consider, in order:

1. Whether the product and affected version are actually present.
2. Whether CISA KEV reports active exploitation.
3. Whether the vulnerable path is exposed, reachable, or invoked.
4. Vendor remediation, fixed-version availability, and compensating controls.
5. CVSS severity and vector, data sensitivity, and operational impact.

`--fail-on` is deliberately a CI exit policy rather than a risk calculator.
`--fail-on none` still reports findings. A KEV item below the chosen severity
threshold should not be ignored, while a Critical result still needs
applicability confirmation before disruptive remediation.

## Project scanner coverage

### OSV-Scanner v2

OSV-Scanner v2 extracts package data and matches it to known vulnerabilities.
For source trees, the default `scan source` path discovers supported manifests
and lockfiles. The auditor requests SARIF 2.1.0 so all three project scanners
share one bounded parser; OSV includes advisory aliases, source locations,
severity properties, and remediation links in that format. Its documented
return codes distinguish findings and operational errors. The normalized
report retains CVSS and CWE evidence when supplied and extracts OSV's
remediation section before bounding it, so fixed-version guidance is not
discarded behind a long advisory.

The auditor uses OSV for dependency evidence, not source-code review. Coverage
depends on a recognized lockfile, manifest, SBOM, or artifact containing an
accurate package version. Dynamic dependencies, private ecosystems, unpackaged
software, unpinned versions, and code copied directly into a repository can be
missed. An advisory may also lack CVSS, a CVE alias, or a fixed version.

Primary sources:

- [OSV-Scanner v2 usage and scan subcommands](https://google.github.io/osv-scanner/usage/)
- [OSV-Scanner outputs, JSON fields, aliases, and return codes](https://google.github.io/osv-scanner/output/)
- [Supported artifacts, manifests, and known limits](https://google.github.io/osv-scanner/supported-languages-and-lockfiles/)

### Trivy filesystem scan

`trivy fs` scans a local filesystem target. Trivy documents vulnerability and
secret scanning as enabled by default; misconfiguration and license scanning
are separately selectable. The auditor explicitly requests vulnerability and
misconfiguration scanning because Gitleaks owns secret detection and
redaction. It uses Trivy's detected package, advisory, severity, fixed version,
and misconfiguration metadata rather than inferring vulnerabilities from
filenames.

Coverage follows the files Trivy recognizes and is affected by exclusions,
generated artifacts, database freshness, target permissions, and scanner
configuration. A filesystem scan is not a live network test, process-memory
inspection, malware verdict, or proof that a configuration is exploitable.
Repository-specific policy can produce false positives or hide accepted
findings, so suppressions need an owner, reason, and review date.

Before each project scanner runs, the auditor reports recognized top-level
ignore/configuration files and scanner-prefixed environment variable names.
It never prints those variable values. This disclosure is deliberately
conservative: nested policy and scanner-default exclusions can still exist,
so the original scanner invocation and repository policy remain part of review.

Primary sources:

- [Trivy filesystem target and scanner behavior](https://trivy.dev/docs/latest/target/filesystem/)
- [Trivy filesystem command reference](https://trivy.dev/docs/latest/references/configuration/cli/trivy_filesystem/)
- [Trivy secret scanner behavior](https://trivy.dev/docs/latest/guide/scanner/secret/)

### Gitleaks

Gitleaks detects secret-like values in Git history, directories, files, or
standard input. The auditor runs both `git` history and `dir` worktree scans
for a repository so uncommitted or untracked files are not omitted. Its current
commands are `git`, `dir`, and `stdin`; the former
`detect` and `protect` commands are deprecated. JSON or SARIF reports include
rule IDs, locations, commits, and fingerprints, and output can redact the
matched secret.

A match is an incident lead, not proof that a credential is valid. A
non-match does not cover unsupported encodings, external secret stores,
deleted remote forks, logs outside the target, memory, or an attacker who has
already copied a credential. Suspected credentials should be revoked or
rotated before history cleanup. Baselines and allow rules reduce noise but can
also conceal a real leak.

Primary source:

- [Official Gitleaks repository, commands, reports, redaction, and limits](https://github.com/gitleaks/gitleaks)

### Why more than one scanner

The tools overlap but are not substitutes:

- OSV answers whether resolved package versions match known advisories.
- Trivy adds broad filesystem inventory and configuration checks.
- Gitleaks specializes in current and historical secret patterns.
- Native host probes answer whether selected operating-system protections
  appear enabled or configured.

`--scanner auto` uses installed tools instead of downloading executables during
an audit. `doctor` reports missing tools and installed versions. A specific
`--scanner` makes coverage reproducible when a pipeline intentionally uses only
one engine.

## Native host checks

Host checks report status; they never change firewall rules, encryption,
update policy, malware protection, Secure Boot, Gatekeeper, or AppArmor.
Managed-device policy can make settings unavailable or intentionally different,
so remediation must be reviewed with the administrator.

### macOS

The useful native signals are whether Gatekeeper application trust is enabled,
whether FileVault protects the startup disk, whether the application firewall
is enabled, and whether automatic Software Update checks are enabled. These are
defence layers, not guarantees:

- Apple describes Gatekeeper, Notarization, and XProtect as complementary
  controls against known malware. Overriding Gatekeeper changes the trust
  decision for that item.
- FileVault limits offline access to disk contents. Recovery-key custody is
  essential; enabling encryption without a recoverable key can cause data
  loss.
- The macOS firewall filters incoming connections and has per-application and
  stealth options. An enabled firewall does not review outbound traffic or
  secure an intentionally allowed vulnerable service.
- Software Update supplies compatible security and stability updates. A
  reported current version does not update third-party software installed
  outside Apple's update channels.
- The native probe currently establishes automatic update checks, not that
  macOS installs every available update. On macOS 26.1 and later, separately
  verify that Background Security Improvements are set to install
  automatically; Apple exposes that control in Privacy & Security.

Primary Apple sources:

- [Gatekeeper, Notarization, and XProtect protections](https://support.apple.com/guide/security/protecting-against-malware-sec469d47bd8/web)
- [FileVault behavior and recovery considerations](https://support.apple.com/guide/mac-help/protect-data-on-your-mac-with-filevault-mh11785/mac)
- [Firewall security in macOS](https://support.apple.com/guide/security/firewall-security-in-macos-seca0e83763f/web)
- [Updating macOS with Software Update](https://support.apple.com/en-us/108382)
- [Apple background updates and Background Security Improvements](https://support.apple.com/en-la/101591)

### Windows

The native view covers Microsoft Defender Antivirus and real-time protection,
Windows Firewall profiles, BitLocker/device encryption, Secure Boot support,
User Account Control, and whether the Windows Update service is disabled:

- Windows Security exposes Defender scan and real-time-protection status.
  Microsoft warns that Defender can turn off when another antivirus product is
  active, so "Defender off" is not automatically "unprotected."
- BitLocker protects data against offline disk access. The recovery key must be
  backed up before relying on encryption.
- Windows Firewall evaluates network traffic per domain, private, and public
  profile. Turning it off or opening broad ports increases exposure.
- Secure Boot permits trusted signed software during the boot process. It does
  not inspect applications after Windows starts and can depend on UEFI
  firmware support.
- Windows devices must also complete the transition from expiring 2011 Secure
  Boot certificates to the 2023 certificates. The auditor reads
  `UEFICA2023Status` and `UEFICA2023Error`; this is distinct from merely seeing
  that Secure Boot is enabled.
- Windows Update provides current security fixes only while the Windows
  version remains supported.

Primary Microsoft sources:

- [Windows Security and Microsoft Defender status areas](https://support.microsoft.com/en-us/windows/security/windows-security/windows-security-app-overview)
- [BitLocker overview and recovery-key requirement](https://support.microsoft.com/en-us/windows/bitlocker-overview-44c0c61c-989d-4a69-8822-b95cd49b1bbf)
- [Firewall and network protection](https://support.microsoft.com/en-us/windows/security/windows-security/firewall-and-network-protection-in-the-windows-security-app)
- [Windows 11 and Secure Boot](https://support.microsoft.com/en-us/windows/security/devicesecurity/windows-11-and-secure-boot)
- [Microsoft's 2023 Secure Boot certificate registry status](https://support.microsoft.com/en-us/topic/a7be69c9-4634-42e1-9ca1-df06f43f360d)
- [Windows Update lifecycle and security updates](https://support.microsoft.com/en-us/windows/deployment/updates-lifecycle/windows-update-faq)

### Ubuntu Linux

Ubuntu's useful native signals are automatic-update service state, AppArmor or
SELinux enforcement, host-firewall status, Secure Boot, root-device encryption,
and selected kernel hardening controls:

- Ubuntu uses backported security fixes during a release's support window, so
  an upstream-looking version number alone is not evidence that a fix is
  absent. `unattended-upgrades` is installed by default on current Ubuntu
  releases but its repository and reboot policy still need verification.
- AppArmor supplies mandatory access control in addition to Unix permissions.
  A loaded module is not the same as every relevant program having an enforced
  profile; complain-mode violations are logged but allowed.
- `ufw` is Ubuntu's simplified frontend to Netfilter and is initially disabled
  by default. An active firewall protects only according to its actual rules;
  it does not repair vulnerable listening services.

Primary Canonical sources:

- [Ubuntu security updates, support windows, and automatic updates](https://documentation.ubuntu.com/security/security-updates/)
- [Ubuntu AppArmor model and enforcing/complain modes](https://documentation.ubuntu.com/server/how-to/security/apparmor/index.html)
- [Ubuntu firewall and `ufw`](https://documentation.ubuntu.com/server/how-to/security/firewalls/)

Other Linux distributions expose different package, firewall, mandatory-access
control, and update interfaces. The auditor can report generic evidence when
available, but Ubuntu is the documented Linux hardening baseline; it must not
label an unrecognized distribution "secure" merely because an Ubuntu command
is absent.

## Safety, privacy, and operational limits

- `audit` and `doctor` are read-only. Findings recommend remediation but do not
  install packages, upgrade dependencies, rotate secrets, rewrite Git history,
  change host policy, or enable security controls.
- The auditor intentionally does not invoke OSV guided fixes or a package
  manager. Dependency changes can execute package scripts, consult
  authenticated registries, and alter lockfiles; review the reported fixed
  versions and vendor advisory before making that separate change.
- `--refresh-kev` retrieves CISA's JSON feed and atomically writes its local
  cache; an explicitly supplied `--kev-catalog` keeps the evidence source
  under caller control. External scanners may maintain their own vulnerability
  databases and caches.
- `--output FILE` is another caller-selected write: it atomically saves the
  complete redacted JSON report with owner-only mode where supported. This
  preserves evidence that a bounded TUI output pane may no longer display.
- Broad targets can traverse unrelated repositories, mounted volumes, caches,
  generated files, and sensitive paths. Filesystem-root scans therefore
  require `--force`, still obey per-check timeouts, and may remain incomplete.
- Scanner databases and the KEV catalog change over time. Record tool versions,
  database/catalog dates, target revision, exclusions, and operational errors
  with every report.
- A structurally valid KEV catalog more than 30 days old is marked `unknown`
  rather than `pass`. This is an auditor freshness guard, not a CISA publication
  promise; a current refresh remains the authoritative check.
- Tools can return false positives, false negatives, duplicate aliases, missing
  severities, and conflicting vendor/NVD scores. Preserve the original scanner
  evidence and confirm remediation against the product vendor's current
  advisory.
- Secret findings are sensitive. JSON reports should be access-controlled and
  must never include unredacted secret material.
- An explicitly selected missing scanner, no usable scanner in `auto`, or an
  installed scanner timeout/parse failure returns operational exit 2 rather
  than a false-success exit 0. Missing optional tools remain visible when
  another `auto` scanner completes. Native checks that cannot prove a setting
  report `unknown`, never `pass`.
- Local checks cannot observe cloud controls, network appliances, identity
  providers, SaaS-side data, firmware posture not exposed by the OS, or remote
  copies of a repository.
- Passing a chosen threshold is not certification against CIS, NIST, PCI DSS,
  HIPAA, ISO 27001, or another framework. Compliance requires an explicit
  scope, control mapping, evidence retention, and accountable review.

The native `system` scope is a posture check, not an installed-package CVE
inventory or a guarantee that every pending vendor update is absent. Use the
operating-system vendor's supported update inventory and endpoint management
alongside this report.

Use the report to decide what to inspect next. For a suspected compromise,
preserve evidence, isolate affected systems where appropriate, rotate exposed
credentials, and follow the organization's incident-response process rather
than treating an automated "fix" as containment.
