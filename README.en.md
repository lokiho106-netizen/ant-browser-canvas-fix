# Ant Browser Canvas crash repair

[中文说明](README.md)

An inspectable, backed-up, reversible workaround for **one exact Windows x64 fingerprint-chromium 150.0.7871.186 build**. It addresses a Canvas pixel-readback defect that can crash renderer processes when fingerprint simulation is enabled.

This is a local community workaround, not an official Ant Browser or Chromium release. No browser binaries, profiles, proxies, credentials, or cookies are included.

## Supported file

- File: `chrome.dll`, size `315028992` bytes.
- Original SHA-256: `6464a50a8f8eae824f85733b52bc42912405390ac7dcb2a7fda7228ea51cbbac`
- Patched SHA-256: `2a2ca874e7944c9496888b07d56c8dd1ed76bf0a2b87c005874fe0a2729bbeed`
- File offset: `0xC392046`; instruction `49 01 C0` becomes `49 89 D0`.

A matching version string is insufficient. The tool rejects unknown complete-file hashes and unexpected instruction bytes. There is no force option. It does not support Linux, macOS, or other builds.

## Usage

Python 3.10+, standard library only. Replace these example paths with your installation paths.

```powershell
python canvas_fix.py inspect --dll "D:\Apps\Ant Browser\chrome\chrome-150\chrome.dll"
```

Stop every instance using that core before applying or restoring:

```powershell
python canvas_fix.py apply --dll "D:\Apps\Ant Browser\chrome\chrome-150\chrome.dll" --backup-dir "D:\Ant-core-backups\canvas-150"
python verify_canvas.py --chrome "D:\Apps\Ant Browser\chrome\chrome-150\chrome.exe"
```

The shared-core repair covers all existing and future instances referencing the same core directory. Restart instances to load it. No per-profile fingerprint or proxy changes are needed.

The verifier uses fresh profiles and a local fixture, with two example seeds and 250 readback/export rounds per seed. Logs stay in ignored `artifacts/`. The repair does not disable Canvas simulation, the sandbox, or certificate validation, and never stops browser processes automatically.

Restore with the original backup path printed by `apply`:

```powershell
python canvas_fix.py restore --dll "D:\Apps\Ant Browser\chrome\chrome-150\chrome.dll" --backup "D:\Ant-core-backups\canvas-150\chrome.dll.6464a50a8f8e.original"
```

Restoring reintroduces the original defect. Replacing or downloading the core again may overwrite the local workaround; inspect it again or adopt an officially fixed upstream build.

## Evidence and attribution

See [the investigation notes](docs/findings.md). The pointer defect and instruction workaround were reported in [upstream issue #94](https://github.com/adryfish/fingerprint-chromium/issues/94), with a related Windows report in [#95](https://github.com/adryfish/fingerprint-chromium/issues/95). This repository packages the known workaround with integrity checks, backup/restore, documentation, and tests; it does not claim original discovery of the upstream defect.

Proxy/TLS failures such as `ERR_CONNECTION_CLOSED` are separate issues. See the [proxy/TLS investigation](docs/network-troubleshooting.md#english-summary) for the domain-versus-IP comparison, limits of the findings, and how to confirm that a running instance actually picked up a proxy change.

```powershell
python -m unittest discover -s tests -v
python -O -m unittest discover -s tests -v
```

Tests use synthetic fixtures, not browser binaries. MIT applies to this repository's new scripts and documentation, not to third-party browser code.
