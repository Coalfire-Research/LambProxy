# Ideas

- Option to specify a "trigger" string. If the server responds with the trigger then the worker is considered burned and it's destroyed and rebuilt and the request issued again. For example, after X number of requests your worker's IP is blocked, Lambscan can optionally detect this and work around it.


