# HireX – Quick‑Start User Guide

## What is HireX?
HireX is an AI‑powered recruitment assistant chat application that lets you build structured **Job Descriptions**, **Screen Candidates**, and **Discuss Results** directly from a web interface.

## User Instructions
Following the instructions below will help you test the application effectively without running into issues.

1. **Open the App** – Navigate to the deployed Azure URL (e.g., `https://hirex-app-xxxx.azurewebsites.net`).
2. **Initial Load** – The application runs on a serverless infrastructure that may spin down when inactive. **The first load may take 1-2 minutes** to wake up the server. Once loaded, you will see existing session chats on the left sidebar.
3. **Application Usage** – Do not run multiple complex tasks at the same time. Wait for one command to finish processing and update the app before running another.
4. **Have Patience** – The application performs several background calls (LLM completions, vector‑search). **Complex queries can take 1-3 minutes**. A spinner (`Thinking…`) indicates the system is processing. **Do not start any other processes meanwhile**; the application will finish the current task before handling the next.

## Getting Started

1. **Create a New Chat** – Click the **New Chat** button to start a new conversation.
2. **Enter Job Description** – Send a message to the assistant with your job requirements. It will guide you to build a structured job description. It extracts what you provide and structures it for your review. You can see the updated job description in the **Job Snapshot** inside the **Active Context** tab.
3. **Start Screening** – When you are satisfied with the extracted **Job Snapshot**, ask the assistant to start screening candidates. It will run a search and show you the results in the chat, including matches and reasoning behind the selection.
4. **Discuss Results** – You can ask the assistant to provide more details about candidates or compare them to help you make a decision.

Enjoy using HireX to streamline your hiring workflow!
After finishing your tests, please share your experience in the Google Form to help us improve the application.
