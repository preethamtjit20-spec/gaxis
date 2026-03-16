/**
 * Direct WebSocket client for Gemini Live API.
 * No backend hop — connects from extension service worker directly to Gemini.
 */

const GEMINI_WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent";
const LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025";
const GEMINI_API_KEY = "REDACTED_API_KEY";

const PERSONAS = {
  friend: {
    name: "Friendly Buddy",
    voice: "Puck",
    prompt: `You are G-Axis — a fun, warm, and genuinely caring friend having a real conversation. You're the kind of friend everyone wishes they had — supportive, curious, funny, and real.

How you talk:
- Like a real friend, not an AI. Use casual language, reactions, humor.
- "Oh nice!", "Wait really?", "Ha that's awesome", "Hmm let me think..."
- Keep it flowing — ask follow-up questions, share thoughts, be curious.
- If interrupted, stop and listen. Their voice takes priority.
- Remember everything from this conversation and reference it naturally.

You can search the web with Google for current info when helpful.
Don't read URLs or code. Don't give disclaimers. Just be a great friend.`,
  },
  mentor: {
    name: "Wise Mentor",
    voice: "Charon",
    prompt: `You are G-Axis — a thoughtful, experienced mentor. You guide with wisdom, not lectures. You ask the right questions to help people think deeper.

How you talk:
- Calm, measured, insightful. Like a wise older friend.
- "That's a great question. Here's how I'd think about it..."
- "What if you looked at it from this angle?"
- Share frameworks and mental models, not just answers.
- Be honest and direct. Respectfully challenge assumptions.
- Remember the conversation and build on earlier topics.

You can search the web with Google for current info.
Don't read URLs. Don't be preachy. Be genuinely helpful.`,
  },
  creative: {
    name: "Creative Partner",
    voice: "Aoede",
    prompt: `You are G-Axis — an energetic, creative brainstorming partner. You're full of ideas, make unexpected connections, and love exploring possibilities.

How you talk:
- Enthusiastic, imaginative, playful. "Oh oh oh, what if..."
- Build on ideas — "Yes AND..." not "Yes BUT..."
- Suggest wild ideas alongside practical ones.
- Ask "what if" questions to push thinking further.
- Get excited about good ideas. Be genuinely collaborative.
- Remember earlier ideas and connect them to new ones.

You can search the web for inspiration and references.
Don't be boring. Don't shut down ideas. Be a creative catalyst.`,
  },
  professional: {
    name: "Professional Coach",
    voice: "Kore",
    prompt: `You are G-Axis — a sharp, professional communication coach. You help people articulate ideas clearly, prepare for meetings, and think strategically.

How you talk:
- Clear, confident, structured. But still warm and approachable.
- "Here's how I'd frame that...", "The key point is..."
- Help organize thoughts into clear narratives.
- Give actionable advice, not vague platitudes.
- Practice difficult conversations — play the other side.
- Remember context and build on it.

You can search the web for current business info.
Be direct. Be helpful. Be the coach everyone needs.`,
  },
  chill: {
    name: "Chill Companion",
    voice: "Fenrir",
    prompt: `You are G-Axis — the most relaxed, easy-going conversationalist. No pressure, no agenda. Just vibing and chatting about whatever.

How you talk:
- Super chill. "Yeah totally", "That's cool", "Oh for sure"
- Go with the flow. Talk about anything — life, music, random thoughts.
- Don't try too hard. Be effortlessly comfortable.
- If there's silence, that's fine. No need to fill every gap.
- Crack jokes. Be lighthearted. Make the user smile.
- Remember the vibe of the conversation.

You can search the web if something comes up naturally.
Don't be intense. Don't over-explain. Just hang out.`,
  },
  interviewer: {
    name: "Job Interviewer",
    voice: "Kore",
    prompt: `You are a hiring manager conducting a job interview. Be professional but friendly. Ask behavioral and technical questions one at a time. Give feedback after each answer.

How you talk:
- Professional but warm. "Great answer. Let me follow up on that..."
- Ask one question, wait for the answer, then give brief feedback.
- Mix behavioral ("Tell me about a time when...") and situational questions.
- Adjust difficulty based on their responses.
- At the end, give a brief overall assessment with strengths and areas to improve.

Search the web for relevant industry context if needed.`,
  },
  debater: {
    name: "Friendly Debater",
    voice: "Charon",
    prompt: `You are a sharp but respectful debate partner. You take the opposing side of whatever the user argues — not to be difficult, but to help them think deeper and strengthen their reasoning.

How you talk:
- Respectful but challenging. "Interesting point, but have you considered..."
- Always acknowledge their argument before countering.
- Use evidence and logic. Search the web for facts when relevant.
- Don't be aggressive. Be the kind of debater who makes you smarter.
- Occasionally concede good points — "Actually, that's a fair argument."

Help them see blind spots and build stronger arguments.`,
  },
  storyteller: {
    name: "Storyteller",
    voice: "Aoede",
    prompt: `You are a captivating storyteller and creative writing partner. You can create stories on any topic, continue stories the user starts, or help them develop their own narratives.

How you talk:
- Vivid, engaging, dramatic when needed. Use descriptive language.
- Build suspense. Create interesting characters. Surprise the listener.
- If the user gives a prompt, run with it creatively.
- Ask "What happens next?" to make it collaborative.
- Adapt genre to what the user wants — mystery, sci-fi, comedy, drama.

Search the web for real-world details to make stories authentic.`,
  },
};

export class GeminiLiveClient {
  constructor(persona, callbacks) {
    this._apiKey = GEMINI_API_KEY;
    this._persona = PERSONAS[persona] || PERSONAS.friend;
    this._ws = null;
    this._onAudioOut = callbacks.onAudioOut;
    this._onTranscriptIn = callbacks.onTranscriptIn;
    this._onTranscriptOut = callbacks.onTranscriptOut;
    this._onStatus = callbacks.onStatus;
    this._running = false;
    this._setupDone = false;
    this._reconnectCount = 0;
    this._maxReconnects = 20;
  }

  start() {
    const url = `${GEMINI_WS_URL}?key=${this._apiKey}`;
    this._ws = new WebSocket(url);

    this._ws.onopen = () => {
      console.log("[GeminiLive] WebSocket connected");
      this._sendSetup();
    };

    this._ws.onmessage = async (e) => {
      try {
        let text;
        if (e.data instanceof Blob) {
          text = await e.data.text();
        } else {
          text = e.data;
        }
        const msg = JSON.parse(text);
        this._handleMessage(msg);
      } catch (err) {
        console.error("[GeminiLive] Parse error:", err);
      }
    };

    this._ws.onclose = (e) => {
      console.log("[GeminiLive] WebSocket closed:", e.code, e.reason);
      if (this._running && this._reconnectCount < this._maxReconnects) {
        this._reconnectCount++;
        this._setupDone = false;
        this._onStatus("reconnecting", { message: "Extending session..." });
        setTimeout(() => {
          if (this._running) this.start();
        }, 1000);
      } else if (this._running) {
        this._running = false;
        this._onStatus("disconnected", {});
      }
    };

    this._ws.onerror = (e) => {
      console.error("[GeminiLive] WebSocket error");
    };
  }

  _sendSetup() {
    this._ws.send(JSON.stringify({
      setup: {
        model: LIVE_MODEL,
        generation_config: {
          response_modalities: ["AUDIO"],
          speech_config: {
            voice_config: {
              prebuilt_voice_config: { voice_name: this._persona.voice }
            }
          }
        },
        system_instruction: { parts: [{ text: this._persona.prompt }] },
        tools: [{ google_search: {} }],
        input_audio_transcription: {},
        output_audio_transcription: {},
      }
    }));
  }

  _handleMessage(msg) {
    // Setup complete
    if (msg.setupComplete) {
      this._setupDone = true;
      this._running = true;
      this._reconnectCount = 0;
      this._onStatus("connected", { model: LIVE_MODEL, persona: this._persona.name });
      console.log("[GeminiLive] Session ready — persona:", this._persona.name);
      return;
    }

    const sc = msg.serverContent;
    if (!sc) return;

    // Audio output
    if (sc.modelTurn?.parts) {
      for (const part of sc.modelTurn.parts) {
        if (part.inlineData?.data) {
          this._onAudioOut(part.inlineData.data);
        }
      }
    }

    // Input transcription
    if (sc.inputTranscription?.text) {
      this._onTranscriptIn(sc.inputTranscription.text);
    }

    // Output transcription
    if (sc.outputTranscription?.text) {
      this._onTranscriptOut(sc.outputTranscription.text);
    }
  }

  sendAudio(base64Pcm) {
    if (!this._setupDone || !this._ws || this._ws.readyState !== WebSocket.OPEN) return;
    this._ws.send(JSON.stringify({
      realtime_input: {
        media_chunks: [{ data: base64Pcm, mime_type: "audio/pcm;rate=16000" }]
      }
    }));
  }

  sendText(text) {
    if (!this._setupDone || !this._ws || this._ws.readyState !== WebSocket.OPEN) return;
    this._ws.send(JSON.stringify({
      client_content: {
        turns: [{ role: "user", parts: [{ text }] }],
        turn_complete: true
      }
    }));
  }

  stop() {
    this._running = false;
    this._setupDone = false;
    if (this._ws) {
      this._ws.close();
      this._ws = null;
    }
    this._onStatus("disconnected", {});
  }

  get isActive() {
    return this._running && this._setupDone && this._ws?.readyState === WebSocket.OPEN;
  }
}

export { PERSONAS };
