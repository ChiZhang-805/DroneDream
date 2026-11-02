# ECE 498 BH course page guide

The **ECE 498 BH** page is a one-screen, interactive course introduction and a
personal student tribute. It is not an experiment runner and is not an official
UIUC or course website.

## Purpose

The page explains how Professor Bin Hu's course, **Applications of Large Language
Models in Engineering**, shaped the engineering method behind DroneDream. The
central lesson is that an LLM proposal is not evidence: tools, structured inputs,
simulation, verification, memory, and feedback must be organized into a bounded
system before a result can be trusted.

DroneDream applies that lesson directly:

1. a model or optimizer proposes a controller candidate;
2. PX4 and Gazebo execute the candidate;
3. artifact and acceptance validators judge the result;
4. failures become structured observations; and
5. the next candidate is selected within explicit safety and cost limits.

The model contributes hypotheses. The harness retains authority.

## Tribute to Professor Hu

The opening card thanks Professor Hu for teaching with exceptional care,
intellectual honesty, and engineering rigor. It also records a classroom memory:
Professor Hu introduced the system-level ideas now commonly discussed as
*harness engineering* before the phrase became familiar to many students. He
connected tools, context, structured outputs, automatic verification, memory,
and feedback loops to real engineering responsibility rather than presenting a
new term in isolation.

Choose **Read the classroom story** to open the longer bilingual tribute. The
dialog traps keyboard focus, closes with Escape or the close icon, restores focus
to its trigger, and prevents the page behind it from scrolling.

## Interactive learning path

The lower panel presents seven milestones from coursework to product. Hover,
focus, or select a milestone to update the adjacent lesson and evidence panel.
Keyboard users can move through the timeline without a mouse.

The stages summarize this progression:

1. **Reasoning baseline** — first measure what the model can do alone.
2. **Tool use** — turn free-form answers into executable engineering actions.
3. **Structured workflow** — make inputs and outputs machine-checkable.
4. **Verification** — separate a plausible answer from a result supported by
   evidence.
5. **Feedback and refinement** — use failures to improve the next attempt.
6. **Final project** — combine the pieces into a domain-specific engineering
   system.
7. **DroneDream** — extend the course discipline into a local-first PX4/Gazebo
   optimization product.

Each stage states both the lesson and its boundary. The page deliberately avoids
claiming that one course assignment alone proves a production system.

## Language and layout

The page has independent English and Simplified Chinese copy. Switching the
application language changes the entire page; mixed-language labels are not
intentional. The layout is designed to fit in one desktop viewport while keeping
the detailed classroom story in a modal.

## External references

The footer links to:

- [Professor Hu's ECE 498 course website](https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html)
- [Professor Bin Hu's homepage](https://binhu7.github.io/)

These links provide the authoritative course and faculty context. The DroneDream
page remains a student's personal appreciation and project retrospective.
