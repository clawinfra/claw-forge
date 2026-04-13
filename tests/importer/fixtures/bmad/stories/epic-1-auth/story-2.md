---
title: User Login
---
Given a registered user,
When they submit valid credentials,
Then the system returns JWT access_token (15min) and refresh_token (7 days).
When they submit invalid credentials,
Then the system returns 401 with "Invalid credentials".
