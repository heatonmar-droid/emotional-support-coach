# Emotional Support Coach: what you can build with this backend

[简体中文](INTRODUCTION.md) · [Project home](../README.en.md) · [Contribute](../CONTRIBUTING.md)

Two people talking about work stress may want very different conversations. One wants to finish telling the story of a difficult day. Another has thought about it for days and wants help organizing the problem. A chat system using one response pattern can offer advice too early or keep asking questions when the user needs something concrete.

Emotional Support Coach provides two switchable modes: everyday support and psychological coaching. It includes a text backend, prompts, and memory code that developers can connect to a mini-program or website, or study independently. The code is MIT-licensed.

This article describes the current repository. All scenarios below are fictional illustrations of intended behavior, not user records, captured model responses, or evidence of effectiveness.

## Two modes with different pacing

Everyday support emphasizes listening and natural conversation. Its prompt asks the model to respond to context rather than repeat a fixed empathy-question-advice sequence or end every turn with a question.

Coaching asks whether enough information is already available. If a key fact is missing, ask a necessary question. If the facts are sufficient, organize them, distinguish options, or suggest a small reversible attempt. Stop pushing when the user does not want to move forward. Coaching here describes a conversational style, not professional credentials or treatment.

| Fictional situation | Everyday support may emphasize | Coaching may emphasize |
|---|---|---|
| “I kept getting interrupted in the meeting. Let me vent first.” | Listening and respecting the request not to analyze | Respecting the same request without forcing an action plan |
| “I've talked about this a lot. How could I talk to my colleague tomorrow?” | Following the request into practical discussion | Sorting facts and boundaries, drafting wording the user can change |
| “Tasks keep piling up. I can't even open the document.” | Understanding the pressure without rushing | When enough is known, reducing the first action to something manageable |

Changing modes does not disable safety assessment or make an exercise appropriate for everyone. Results still depend on the model, prompts, and current context; evaluate them with concrete cases.

## Where it can fit

**Emotional-support chat in a mini-program or website.** Connect your interface to APIs that handle context, account isolation, and completed replies. The repository has a standalone account-token adapter, but no complete registration platform, payments, or operations dashboard.

**Conversation prototypes about stress, relationships, or next steps.** Let users choose between listening-oriented and organizing-oriented conversations, then evaluate whether that distinction fits the product. The modes share storage and memory rather than requiring two separate systems.

**Prompt and memory experiments.** Main prompts and shared rules are separate files. Use invented conversations to check repeated questioning, whether guesses become stored facts, and whether corrections replace outdated information. The offline tests provide a starting point.

**Method-card retrieval experiments.** Import the bundled cards and compare responses with and without retrieval. Finding a relevant card does not establish that an exercise is appropriate or that a response improved.

## What happens during a turn

The server authenticates the account token, then reads that account's mode, recent context, and relevant memories. Supplying a user ID in the request cannot substitute for authentication. Imported method cards are retrieved when available.

Safety assessment and ordinary reply generation run in parallel. The safety result determines the response path. The final payload must pass structural checks and be saved successfully before the API emits completion. A length-truncated reply gets one bounded retry; an incomplete assistant reply is not stored as a normal result.

The frontend receives progress and results through SSE. The current protocol emits the reply after complete generation, **not token by token**. Wait for `workflow_end` or handle `error`; HTTP 200 alone is insufficient.

Memory extraction runs in the background after replies. See [architecture](ARCHITECTURE.md) for details and limitations.

## Different kinds of memory

Recent context helps the model follow the conversation, within message-count and character limits. It does not include unlimited history.

Profile memory in PostgreSQL holds potentially useful cross-session information. Episodic memory uses Mem0 OSS and Qdrant to retrieve relevant events. Proposed memory writes are checked against user quotes; corrections and forgetting operations are constrained by account and record scope.

In a fictional test, a user might first say “I'm preparing to change jobs,” then correct it to “I've decided to stay for now.” Check whether outdated information becomes inactive and later replies use the correction, rather than merely checking that another database row exists.

More memory is not automatically better. Prompts treat memories as references, not instructions to bring up the past on every turn or redirect users to topics they want to leave alone.

Not using information and physically erasing it are different operations. Natural-language forgetting may invalidate profile entries while original chats remain. Reset does not promise to delete provider-retained data, backups, or Mem0 operation history. See [privacy boundaries](PRIVACY.md).

## How the 68 method cards are used

The cards include situations, purpose, instructions, and stopping boundaries. Topics include grounding, distancing from thoughts, values, small actions, and interpersonal expression. Card text remains Chinese.

The database starts empty. Cards participate in retrieval after you configure embeddings and import them. Retrieval considers the current message and recent context; the reply model decides whether to use the reference. A retrieved card should not override a user's refusal to try an exercise.

Cards are not full treatment plans. The repository includes no real counseling transcripts, user memories, or book full text. Third-party publications appear only in an inventory; their copyrights are not covered by the code's MIT license. See [knowledge notes](../knowledge/README.md).

## Developers choose the models

Reply generation, safety assessment, and memory extraction are configured by role. Roles can share a model or use different ones. Deployment-specific model IDs are not supplied; fill in your own endpoints, credentials, and model names.

The chat adapter uses OpenAI-compatible Chat Completions and requires the project's structured-output contract. Other protocols need an adapter. Retained mode IDs `claude` and `claude_coach` do not restrict model choice.

Embedding models and endpoints are configurable too, but the current store requires 1024-dimensional output. Rebuild card and episode vectors when changing embedding models. Equal dimensions do not make different embedding spaces compatible.

Getting text back is only the beginning. Verify formatting, truncation handling, memory quote checks, and safety behavior. Compatible endpoints do not guarantee equivalent model behavior.

## First, complete one fictional turn

Follow the [quick start](../README.en.md#quick-start): clone, install dependencies, prepare an empty database, and fill in configuration. Initialize the schema, create a test account, and start one worker.

Try a fictional input such as “I have three things to do tomorrow and want to decide their order.” Check authentication and completion first, then verify that your history endpoint contains the turn. Repeat a fictional scenario in the other mode to compare behavior without assuming one mode must be better.

For cross-session memory, allow background work to finish and verify both storage and retrieval. A reply that does not mention an earlier fact is not by itself proof of storage failure; the model may have chosen not to use it.

Without model credentials, you can still read prompts and run model-double tests. Database integration requires a separate local test database and explicitly skips otherwise. See [validation notes](VALIDATION.md) for completed checks and remaining gaps.

## What deployers still need to provide

This is backend code rather than a complete consumer product. Supply your own frontend, identity integration, rate limits, and monitoring. The current adapter requires one process and one worker, with a global lock coordinating requests. It suits development and small-scale evaluation; high-concurrency operation is not validated. Background memory jobs are not durable, so process exit can lose unfinished extraction work.

Self-hosting does not imply offline processing. Messages and relevant context may go to configured model and embedding services. Explain those data flows to users.

The project has not been clinically validated. It makes no diagnosis or treatment claims and is not an emergency-help channel. English prompts are reference translations, not evidence of a validated English-language service or localized safety guidance for every region.

## Contribute something concrete

A missing setup step, a fictional case that causes repeated questioning, or a translation that changes meaning can all make useful contributions. Open an issue or fork the repository and submit a PR; maintainers review merges.

Running the quick start, proofreading, and adding fictional regression cases also help. Keep real chats, user memories, credentials, and database exports out of public discussions.

[Repository](https://github.com/heatonmar-droid/emotional-support-coach) · [Contribution guide](../CONTRIBUTING.md) · [Issues and ideas](https://github.com/heatonmar-droid/emotional-support-coach/issues/new/choose)
