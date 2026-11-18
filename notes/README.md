# `ai-service` notes, day by day

Notes are grouped by **day**. Inside a day they follow **the order of the plan's tasks, which is also the order things were built**, so reading a folder from the first file to the last follows the build. Each day has its own `questions/` folder with the questions I asked while reading that code, in the same order.

| Day | Folder | What it covers | Start with |
|---|---|---|---|
| **3** | [day-3/](day-3/README.md) | The base service: FastAPI, async SQLAlchemy, auth, documents, middleware, SSE, tests, Docker | [day-3/README.md](day-3/README.md) |
| 4 | (no code here) | LLM fundamentals: notes are in `ai-eng-learning/day-4/` | |
| **5** | [day-5/](day-5/README.md) | `/chat` (streaming, stored) and `/extract` (structured output) | [day-5/README.md](day-5/README.md) |
| **6** | [day-6/](day-6/README.md) | Reliability, cost and providers: retry, fallback, limits, cost logging, prompt caching, 50 messy inputs | [day-6/README.md](day-6/README.md) |
| **7** | [day-7/](day-7/README.md) | Prompt engineering: the prompt registry and a measured prompt comparison (in progress) | [day-7/README.md](day-7/README.md) |

## What is in each day folder
```
day-N/
  README.md        the day's tasks mapped to notes, in order
  NN-*.md          the notes, in task / implementation order
  questions/       my questions and the answers (README.md has the index)
  explanation/     (day 6 only) every source file explained line by line
```

## Other files
- [00-reading-guide.md](00-reading-guide.md): how to read the whole project from `main.py`, step by step, day by day.
- `decisions.md` and `gotchas.md` (project root): the numbered decisions and the traps found by running the code.
- `ai-eng-learning/day-N/`: the concept notes written before building (learning) and the real results (Notes).

## Where each day's questions come from
- Day 3 questions: [day-3/questions/](day-3/questions/README.md) (Q1 to Q22).
- Day 5 questions: [day-5/questions/](day-5/questions/README.md) (Q23 to Q30, plus a note of short questions).
- Day 6 questions: [day-6/questions/](day-6/questions/README.md) (Q31 to Q42).
- Day 7 questions: [day-7/questions/](day-7/questions/README.md) (Q43 onward).
