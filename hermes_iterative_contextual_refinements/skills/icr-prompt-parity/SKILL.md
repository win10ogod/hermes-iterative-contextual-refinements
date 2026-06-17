---
name: icr-prompt-parity
description: Verify and maintain ICR prompt parity against bundled upstream prompt resources, including source checksums, extracted role system prompts, and runtime prompt-builder wording.
---

# ICR Prompt Parity

Use this skill when checking whether the Hermes ICR plugin preserves upstream prompt behavior.

## Source Of Truth

The plugin bundles upstream prompt resources under `hermes_iterative_contextual_refinements/source_prompts/`:

- `DeepthinkPrompts.ts`
- `ContextualPrompts.ts`
- `AdaptiveDeepthinkPrompt.ts`
- `AgenticModePrompt.ts`
- `DCAPrompts.ts`

Do not replace these with short summaries. The runtime loader extracts template literals from these files and uses them for role system prompts.

## Verification

Run the test suite and confirm:

- source prompt SHA-256 checksums match `SOURCE_PROMPT_SHA256`
- Deepthink role system prompts come from `load_deepthink_prompts()`
- Contextual, Agentic, Adaptive, and DCA system prompts come from source prompt resources
- prompt-builder tests still include upstream wording such as `Return only JSON`, `genuinely novel, fundamentally distinct`, and `Relevant Context For Your Current Strategy`

For an installed package, run:

```bash
python -m hermes_iterative_contextual_refinements.prompt_parity
```

or the console script:

```bash
icr-prompt-parity
```

The command exits nonzero if a bundled source prompt checksum, extracted system prompt, or critical runtime prompt-builder fragment has drifted.

## Change Discipline

If upstream prompt files are refreshed, update the copied resource files and `SOURCE_PROMPT_SHA256` together in the same change. Do not modify a copied upstream prompt in place unless the change is explicitly intended to diverge from upstream and documented as a plugin-specific fork.
