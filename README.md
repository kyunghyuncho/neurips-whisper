# NeurIPS Whisper

**Motivation**: I wanted to see if I could create a Twitter-like app but for a private event, inspired by NeurIPS that's starting today (December 1 2025).

## How I Started
I started by asking **Gemini 3 Pro** at https://gemini.google.com/. This helped me think of all the way to how I would deploy it eventually (e.g. using Railway). After that, I used **Antigravity** from Google to build the implementation.

## Features
*   **Real-time Feed**: Live updates of new whispers from attendees.
*   **Threaded Conversations**: Reply to whispers to start a discussion.
*   **Magic Link Authentication**: Secure, passwordless login via email.
*   **Rich Text Support**: Messages support Markdown, clickable links, and hashtags.
*   **Search & Discovery**: Easily find whispers by keywords or hashtags.

## Critical Modules
*   **[Resend](https://resend.com)**: For sending authentication magic links.
*   **[Redis](https://redis.io)**: Used for caching and real-time data features.
*   **[PostgreSQL](https://www.postgresql.org)**: Primary database for persistent storage.
*   **[FastAPI](https://fastapi.tiangolo.com)**: High-performance web framework for the backend.

## Deployment
Deployment is designed to be easy, with configuration ready for platforms like **Railway**. The project includes standard `Procfile` and `runtime.txt` definitions.

## Disclaimer
> [!NOTE]
> This project is still a **work in progress**. Features are subject to change.

## Credits
Developed by **Kyunghyun Cho** as part of **KC Explorer LLC**.