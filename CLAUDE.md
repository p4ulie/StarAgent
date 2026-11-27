# StarAgent

## Workflow

- Session roles (owner, 2026-11-27): the Eve apps (eve-builder, eve-universe, eve-agent, staragent) belong to one
  session (`eve-apps`): only it changes their code, tags and images. The `homenet` session owns homenet_2.0 and
  deploys (pins move there on the owner's "deploy" word). When homenet needs an app change it messages `eve-apps`
  with the card, the files and the constraints; `eve-apps` builds it and replies with the version. Any other
  session that finds an app change to make messages `eve-apps` (SendMessage; ListAgents shows who runs) or, with no
  live `eve-apps` session, files it as a card on the Eve Builder board instead of building it.
