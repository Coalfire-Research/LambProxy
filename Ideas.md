# Ideas

- Lambproxy is pretty slow right now. It takes around 3 seconds to get a reply from the lambda function. Even just a blank function that simply returns without doing anything takes 2-3 seconds to execute. How can this be sped up?
  - Maybe the workers can be spun up ahead of time and listening on a reverse socket so they are ready to go? This is less efficient and more expensive though.


