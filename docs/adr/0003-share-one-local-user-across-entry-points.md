# Share one local User across entry points

Version 0.2 is a trusted local single-user application. Web and CLI resolve the same automatically created, persistent local User, represented by Django's built-in User model with an unusable password, so ownership and User Memory remain stable across entry points and restarts; login credentials, API tokens, multiple Users, custom User models, and client-supplied `user_id` values are outside this version's scope.
