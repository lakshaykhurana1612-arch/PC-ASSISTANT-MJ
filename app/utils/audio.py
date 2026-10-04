import pyttsx3
import speech_recognition as sr

engine = pyttsx3.init()
voices = engine.getProperty('voices')
engine.setProperty('voice', voices[0].id) 
engine.setProperty('rate', 170)

def speak(text):
    print(f"MJ: {text}")
    engine.say(text)
    engine.runAndWait()

def listen():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n[Listening... Speak now]")
        # Give it a full second to calibrate to your room's background noise
        recognizer.adjust_for_ambient_noise(source, duration=1) 
        
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
            print("[Processing...]")
            
            # Note: recognize_google requires internet to convert speech to text
            text = recognizer.recognize_google(audio) 
            print(f"You: {text}")
            return text.lower()
            
        except sr.WaitTimeoutError:
            # It listened for 5 seconds but heard absolute silence
            pass 
        except sr.UnknownValueError:
            print("[MJ heard you, but couldn't understand the words.]")
        except sr.RequestError:
            print("[MJ needs an active internet connection for Speech-to-Text.]")
        except Exception as e:
            print(f"[Microphone Error: {e}]")
            
        return ""