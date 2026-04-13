---
title: User Registration
---
Given a visitor on the registration page,
When they submit email and password,
Then the system creates an account and returns 201 with user_id.
When they submit a duplicate email,
Then the system returns 409 with "Email already registered".
