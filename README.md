### About

DEX Sonar is a telegram bot that simplifies trading on decentralized exchanges (DEXes). It constantly searches pre-defined patterns in token charts and sends a message to a user in the case of a match. It also provides essential information about the token pool, such as fully distributed value (FDV), liquidity, token address, and links to tracking services. The bot visualizes the price chart without fragmenting the timeframe and volume curve, which many popular screener services do not offer.

<img src="https://i.imgur.com/KSDXliY.jpeg" width="810" >

Currently, the bot is only working on the TON blockchain. Its main direction is short-term trading or flipping. An example of usage can be a dump detected by a bot. A dump is a sharp price drop often caused by the whale exit (a single maker selling a large token amount in a short-term period). If a token is reliable and shows global growth, it is an excellent chance to buy the asset. In this case, tokens are often bought off by other makers very rapidly, which is demonstrated in the picture below. The average profit from such one flip can achieve $50-$200 depending on pool liquidity and deposit (the P&L of the depicted example is ~$90). The average flip time is usually between 3 minutes and 30 minutes.

<img src="https://i.imgur.com/VYZjzm2.jpeg" width="732">

### Work in progress

- Solana blockchain support
- RNNs for short-term price prediction (5-15 min)
- Scam detector via binary classifier (e.g honeypots)
- More sophisticated patterns (monotony property, custom function support for pattern match bound for different timeframes)
- Relative price change notifications for selected tokens (very useful for notifications about selling (exit) point)

### Access

The bot is not meant to be publicly accessible. In order to acquire access, you need to contact the owner and to be added to the database whitelist.
