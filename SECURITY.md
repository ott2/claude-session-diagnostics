# Security

## What this tool does

`csd` reads Claude Code session transcripts from a directory that you name, and
writes a report to standard output. It makes no network request, starts no
subprocess, and writes no file. It parses JSON with the standard library.

It never sends your transcripts anywhere.

## What your transcripts contain

Session transcripts hold the content of your conversations, the paths of the
files you worked on, and the name of each project. They are private data.

`csd` prints project labels and session identifiers in its reports. Before you
paste output into an issue, remove anything that you do not want to publish.
`--project-depth 1` makes the project labels shorter.

## Supported versions

Fixes are applied to the most recent release only.

| Version | Supported |
|---|---|
| 1.0.x | yes |

## Report a vulnerability

Use GitHub private vulnerability reporting:

1. Open the **Security** tab of this repository.
2. Select **Report a vulnerability**.

Please do not open a public issue for a security problem.

Include the version, the command that you ran, and what happened. A transcript
that causes the fault is useful, but remove any private content from it first.

You can expect a first response within 14 days. This is a small project that one
person maintains, so please allow reasonable time for a fix.

## Scope

In scope:

- code execution, file writes, or network access caused by parsing a transcript
- a crafted transcript that causes the tool to read a file outside the root that
  you named
- a fault in the GitHub Actions workflows that would let a pull request obtain
  write access to this repository

Out of scope:

- incorrect cost figures. These are a correctness problem, not a security
  problem. Open a normal issue.
- the figures in `FINDINGS.md`. They come from one corpus and are stated as
  hypotheses to test.
