# Locate Memory Spaces by workspace path

Version 0.2 uses the canonical absolute path of a local workspace or code repository to find or create the local User's persistent Memory Space. The Memory Space keeps its own stable ID, and only that ID reaches Memory; moving or renaming the workspace creates a new Memory Space, while migration and rebinding are deferred.
