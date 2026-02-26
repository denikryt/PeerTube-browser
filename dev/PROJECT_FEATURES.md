# PROJECT TASKS

---

## ENGINE

1. Perform a major refactor to fully separate Engine from Client as an independent service.

2. Design and formalize the API contract for Client ↔ Engine interaction.

3. Implement independent production deployment for Engine.

4. Implement a full development mode for Engine.

5. Implement install / uninstall processes for Engine (dev / prod).

6. Simplify build and data build to a “single command” workflow.

7. Design and implement a public REST API.

8. Implement API versioning.

9. Implement an access token system (API keys) for Engine.

10. Implement token management (creation, revocation, limits, moderation).

11. Implement API-level rate limiting (including limits per token, IP, instance).

12. Implement IP and instance-level blocking and restriction mechanisms.

13. Implement input size limits and request validation.

14. Implement a roles and permissions system (RBAC).

15. Implement database migration system.

16. Implement data backup mechanism (database and indexes).

17. Implement a task queue system for heavy operations.

18. Implement content feed modes:

* random
* hot
* popular
* fresh
* recommendations

19. Implement endpoint `similar(video_id)`.

20. Implement endpoint `recommendations(list_of_video_ids)`.

21. Implement a dedicated search API.

22. Implement scoped recommendations based on a specified instance.

23. Implement crawler with federated scope limitation.

24. Implement ActivityPub actor for Engine.

25. Implement follow logic and processing of incoming ActivityPub updates.

26. Implement deduplication of incoming ActivityPub activities.

27. Implement intake of user interactions (likes, comments) for scoring.

28. Implement receiving and processing personalization parameters from Client.

29. Implement incremental vector and index recalculation.

30. Implement full index recalculation mechanism.

31. Migrate to video-ID-based indexing.

32. Ensure proper content deletion without full index recalculation.

33. Implement Engine moderation system (ban instances, ban channels).

34. Implement public Engine dashboard (open statistics).

35. Implement collection and exposure of statistical data (instances, videos, channels, load, updates, tokens).

36. Implement display of blocked / active / new instances in the dashboard.

37. Implement moderation and data management interface for Engine via UI.

38. Implement UI for Engine analytics (metrics, resource usage, token activity).

39. Enable third-party instances to use Engine via API (plugin-like scenario).

40. Migrate Engine HTTP server from ThreadingHTTPServer to FastAPI (ASGI)

---

## CLIENT

1. Perform a major frontend refactor (replace static HTML/CSS).

2. Introduce a scalable frontend framework and component-based architecture.

3. Design and implement a unified design system.

4. Implement responsive and mobile-friendly interface.

5. Implement Home page (feed modes, video cards, dynamic loading).

6. Implement video search page.

7. Implement Video page (player, comments, related/up next section).

8. Implement user registration.

9. Implement authentication and session management (including multiple login methods).

10. Implement user profile (avatar, nickname, settings).

11. Implement user data export mechanism.

12. Implement storage of user likes and comments in database.

13. Implement like/dislike functionality (add/remove).

14. Implement sending likes and comments via ActivityPub to original instance.

15. Implement sending user interactions to Recommendation Engine.

16. Implement user reporting mechanism (report + reason).

17. Implement moderation dashboard.

18. Implement client-side moderation system (ban users, remove comments).

19. Implement user personalization panel for recommendation parameters.

20. Implement proper integration with Engine API (auth-aware requests, validation, rate limiting).

21. Implement client-side security hardening (XSS, CSRF, session protection).

22. Implement independent production deployment for Client.

23. Implement development mode for Client.

24. Implement install / uninstall processes for Client (dev / prod).

30. Migrate Client backend HTTP server from ThreadingHTTPServer to FastAPI (ASGI)
---

## PRESENTATION WEBSITE & DOCUMENTATION

1. Create a separate presentation website for the project.

2. Describe the architecture (Engine + Client + interaction model).

3. Describe platform capabilities and usage scenarios.

4. Add a section about the public API and integration possibilities.

5. Add links to live demo / UI.

6. Prepare full technical documentation:

   * installation
   * startup
   * deployment
   * data build
   * API usage

7. Provide clear documentation for third-party developers who want to use Engine.
