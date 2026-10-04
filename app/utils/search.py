from ddgs import DDGS

def search_web(query):
    try:
        with DDGS() as ddgs:
            # Query ko filter karo taaki news articles na aaye
            # 'h' timelimit matlab last 24 ghante
            results = list(ddgs.text(f"{query} winner score", max_results=1, timelimit="d"))
            if results:
                # Sirf body return karo
                return results[0]['body']
            return "Boss, kal ke match ka data nahi mil raha."
    except Exception as e:
        return f"Error: {e}"