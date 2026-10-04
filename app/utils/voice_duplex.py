from app.utils.voice import listen, speak

def start_duplex():

    # Lazy imports to avoid circular import
    from app.utils.actions import execute_smart_action
    from app.brain.groq_client import analyze_command_with_ai

    speak("Duplex mode activated Boss.")

    while True:

        text = listen()

        if not text:
            continue

        if text.lower() in [
            "exit duplex",
            "close duplex",
            "stop duplex"
        ]:
            speak("Leaving duplex mode Boss.")
            break

        ai = analyze_command_with_ai(text)

        if ai:
            result = execute_smart_action(ai)

            if result:
                speak(result)