# TA2 Project Extension: Testing and Report Generation Guide

This guide provides a step-by-step approach to testing your Unit 3 and Unit 4 implementations and compiling the final 4-page report required for your TA2 submission. 

## Part 1: How to Test Your TA2 Project

Before testing, ensure your TA1 baseline is frozen in a `ta1/` folder and you are developing exclusively in `ta2/` using **Ollama (qwen2.5:3b)** and **nomic-embed-text**.

### 1. Define Your 5 Test Cases (Evaluation - EV)
You must run the exact same 5 test cases on both your frozen TA1 baseline and your new TA2 system. 
*   **Design the cases:** Ensure they test memory (follow-up questions), RAG (domain-specific queries), and multi-agent routing (complex tasks requiring delegation).
*   **Record:** Save the console output (traces) for every run.

### 2. Testing Unit 3 Components (Memory & RAG)
*   **Test U3-1 (Short-term Memory):** Run a multi-turn conversation. Ask a follow-up question that relies on context from the first turn. 
    *   *Evidence:* Save the trace showing successful recall, and one trace showing "amnesia" (without memory).
*   **Test U3-2 (Long-term Memory):** Create a user profile or state. Stop the script, restart it, and ask the agent to recall the data.
    *   *Evidence:* Trace of the restart demo proving SQLite persistence.
*   **Test U3-3 (RAG):** Ask a question that requires your document chunks (at least 8 chunks in Chroma). 
    *   *Test unanswerable:* Ask a question completely outside the corpus. The agent MUST say "I don't know" (or similar).
    *   *Evidence:* Trace comparing retrieval with $k=1$ versus $k=3$, and the unanswerable question trace.
*   **Test U3-4 (Tool Failure):** Intentionally inject a tool failure (e.g., force an API or calculation to error out).
    *   *Evidence:* Trace showing the agent catching the error and recovering/explaining it.

### 3. Testing Unit 4 Components (Multi-Agent & Safety)
*   **Test U4-2 (Coordination):** Trigger a complex query that requires the Supervisor to route to different agents. 
    *   *Evidence:* Annotated routing trace showing the hops and ensuring it respects `MAX_HOPS`.
*   **Test U4-3 (Oversight/Guardrails):** Attempt a prompt injection attack OR trigger the human-in-the-loop approval step.
    *   *Evidence:* Traces showing both an approved path and a rejected path.
*   **Test U4-4 (Challenge Analysis):** Pick one metric to measure during your 5 test cases:
    *   *Cost:* Count the number of LLM calls or measure execution time.
    *   *Errors:* Track error propagation across agents.
    *   *Safety:* Number of successful vs blocked prompt injections.

---

## Part 2: How to Structure the Final Report

Your final report must be a **PDF of at most 4 pages**. Use the following structure to ensure you hit every rubric requirement.

### 1. Title & Contribution Table
*   **Group Info:** Group NN, Division, Topic.
*   **Contribution Table:**
    | Member Name | Module Owned (e.g., Memory, RAG, Supervisor) | Specific Contribution |
    | :--- | :--- | :--- |
    | Student 1 | RAG & Long-term Memory | Built Chroma integration, tested k=1 vs k=3 |

### 2. Architecture Diagram
*   Include a visual diagram showing the flow between the User, Supervisor/Router, the distinct Role Agents, the Memory Stores (SQLite/Checkpointer), and the RAG Corpus (Chroma).

### 3. Role Design (U4-1)
Provide the 5-field spec for *every* agent in your system.
*   **Agent 1: [Name]**
    *   **Goal:** [What it tries to achieve]
    *   **Tools:** [List of tools it can access]
    *   **Inputs/Outputs:** [What it takes in / what it returns]
    *   **Limits:** [Constraints, e.g., MAX_HOPS or prompt limits]

### 4. Component Checklist & Evidence Pointer
Create a checklist mapping the requirements to your `traces/` folder.
*   [x] **U3-1 (Short-term):** See `traces/u3_1_memory.txt`
*   [x] **U3-2 (Long-term SQLite):** See `traces/u3_2_restart.txt`
*   [x] **U3-3 (RAG & Unanswerable):** See `traces/u3_3_rag_k_compare.txt`
*   [x] **U3-4 (Tool Failure):** See `traces/u3_4_failure.txt`
*   [x] **U4-2 (Supervisor/Routing):** See `traces/u4_2_routing.txt`
*   [x] **U4-3 (Guardrail/Approval):** See `traces/u4_3_oversight.txt`

### 5. Evaluation: TA1 vs TA2 (EV)
Present the results of your 5 test cases in a comparison table. Include a paragraph explaining what improved and what degraded (e.g., TA2 might be slower or loop too much).

| Test Case | TA1 Baseline Result | TA2 Extended Result | Improvement/Degradation |
| :--- | :--- | :--- | :--- |
| 1. [Query] | Failed (No context) | Passed (RAG retrieved answer) | Better accuracy, slower response |

### 6. Challenge Analysis (U4-4)
Present a short table with hard numbers based on your chosen challenge metric (e.g., Token counts, execution time per test case, or routing loop counts). *Do not use opinions here, only measured data.*

### 7. Limitations and Next Steps
*   Honestly report any failures (e.g., "The 3B model struggled with complex routing in Test Case 4..."). Remember, a documented failure with analysis scores better than a hidden one.
*   State what you would do next to improve the system.

### 8. AI Declaration
*   *Required:* "AI Assistance Note: We used [Tool Name] to help debug [specific error] and understand [concept]. No AI was used to generate the report or the core extension code."