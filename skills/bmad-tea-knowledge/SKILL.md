---
name: bmad-tea-knowledge
description: Use when a testing skill needs a knowledge fragment on fixtures, network-first safeguards, test levels, priorities, data factories, CI burn-in, or any other testing pattern — this is where those fragments live.
license: MIT
metadata:
  author: ai-playbook
  derived_from: "BMAD Method Test Architecture Enterprise tea@1.7.2 (imported 2026-04-26) — MIT, (c) 2025 BMad Code, LLC"
  notice: ../../NOTICE
  version: "1.0"
---

# bmad-tea-knowledge — shared knowledge base for the testing skills

This skill holds no workflow. It is the single copy of the testing knowledge
base that every `bmad-testarch-*` skill and `bmad-tea` read from.

## Why it exists

The knowledge base used to be duplicated: the same 49 fragments and the same
index sat inside nine skill directories, byte for byte identical, and every one
of them was copied again into three mirrors in every consumer repository. One
copy of a fragment was reaching a consumer twenty-seven times.

Keeping one copy here removes about six megabytes from this repository and the
same duplication from every consumer, and it means a correction to a fragment is
made once instead of nine times.

## How to use it

Fragments are selected through an index, never by browsing the directory:

1. Read `../bmad-tea-knowledge/resources/tea-index.csv`. Each row carries an
   `id`, a description, tags, a tier, and the fragment's path.
2. Match the current task against the description and tags, and take only the
   fragments you need.
3. Load them from `../bmad-tea-knowledge/resources/knowledge/`.

Paths are relative to the calling skill's own directory. Every skill that reads
this base is materialised alongside it, in the same parent directory, so the
same relative path resolves both here and in a consumer repository.

Loading the whole base is a mistake: it is far larger than any single task
needs, and the index exists so that a task pays only for the fragments it
actually uses.

## What belongs here

A fragment belongs here when more than one testing skill needs it. Anything
specific to a single skill stays with that skill, so this base does not become
the place where testing content accumulates by default.
