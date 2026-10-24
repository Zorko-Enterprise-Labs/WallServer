# WallServer

Turn a TV into a shared wall for your home network. Drag a file onto a small window on your PC
and it appears on the TV within seconds, with a live progress card while it's sending.
Pictures, videos, PDFs and text files show up directly; anything else shows as a file card.

The wall can show one, two, three or four things at once. You can pin slots so they don't get
replaced, black out the screen, and control it all from your phone.

It has two parts:

- **[WallServer](WallServer/)** runs on the machine connected to the TV (Windows, or a Raspberry
  Pi / Linux) and shows the wall fullscreen in a browser.
- **[WallClient](WallClient/)** runs on your PC. It's a drag-and-drop window, plus an
  optional right-click **Send to → Wall** entry and a command-line `send.py`.

Both need Python 3.10 or newer. Setup steps are in each part's README.

Senders need a token, which WallServer generates the first time it starts. Traffic is plain HTTP,
so use it on a network you trust, such as your home network.

## License

[Apache-2.0](LICENSE)
