This is a repository for client-side HTML/CSS/JavaScript WebRTC code samples.

Many of the samples use new browser features. They may only work in Chrome Canary and/or Firefox Beta, and may require flags to be set.

All of the samples use [adapter.js](https://github.com/GoogleChrome/webrtc/blob/master/adapter.js), a shim to insulate apps from spec changes and prefix differences. In fact, the standards and protocols used for WebRTC implementations are highly stable, and there are only a few prefixed names. For full interop information, see [webrtc.org/interop](http://www.webrtc.org/interop).

NB: all samples that use `getUserMedia()` must be run from a server. Calling `getUserMedia()` from a file:// URL will result in a PERMISSION_DENIED NavigatorUserMediaError.

For more information about WebRTC, we maintain a list of [WebRTC Resources](https://docs.google.com/document/d/1idl_NYQhllFEFqkGQOLv8KBK8M3EVzyvxnKkHl4SuM8/edit). If you've never worked with WebRTC, we recommend you start with the 2013 Google I/O [WebRTC presentation](http://www.youtube.com/watch?v=p2HzZkd2A40).

Patches and issues welcome!

The demos
=========

[Constraints and stats](http://googlechrome.github.io/webrtc/samples/web/content/constraints)

[Display createOffer output](http://googlechrome.github.io/webrtc/samples/web/content/create-offer)

[Data channels](http://googlechrome.github.io/webrtc/samples/web/content/datachannel)

[DTMF](http://googlechrome.github.io/webrtc/samples/web/content/dtmf)

[Face tracking](http://googlechrome.github.io/webrtc/samples/web/content/face)

[Simple getUserMedia() example](http://googlechrome.github.io/webrtc/samples/web/content/getusermedia)

[getUserMedia() + Canvas](http://googlechrome.github.io/webrtc/samples/web/content/canvas)

[getUserMedia() + Canvas + CSS Filters](http://googlechrome.github.io/webrtc/samples/web/content/filter)

[getUserMedia() with resolution constraints](http://googlechrome.github.io/webrtc/samples/web/content/resolution)

[getUserMedia() with camera/mic selection](http://googlechrome.github.io/webrtc/samples/web/content/sources)

[ICE Candidate gathering](http://googlechrome.github.io/webrtc/samples/web/content/trickleice)

[Audio-only getUserMedia() output to local audio element](http://googlechrome.github.io/webrtc/samples/web/content/getusermedia-audio)

[Audio-only getUserMedia() displaying volume](http://googlechrome.github.io/webrtc/samples/web/content/getusermedia-volume)

[Streaming between two RTCPeerConnections on one page](http://googlechrome.github.io/webrtc/samples/web/content/peerconnection)

[Audio-only peer connection](http://googlechrome.github.io/webrtc/samples/web/content/peerconnection-audio)

[Multiple peer connections](http://googlechrome.github.io/webrtc/samples/web/content/multiple)

[Multiple relay](http://googlechrome.github.io/webrtc/samples/web/content/multiple-relay)

[Munge SDP](http://googlechrome.github.io/webrtc/samples/web/content/munge-sdp)

[Accept incoming peer connection](http://googlechrome.github.io/webrtc/samples/web/content/pr-answer)

[Peer connection rehydration](http://googlechrome.github.io/webrtc/samples/web/content/rehydrate)

[Peer connection states](http://googlechrome.github.io/webrtc/samples/web/content/peerconnection-states)

[Web Audio output as input to peer connection](http://googlechrome.github.io/webrtc/samples/web/content/webaudio-webrtc)
