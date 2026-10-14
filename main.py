from content_agent import ContentAgent

def main():
    print("Instagram Manager Agent Started")

    agent = ContentAgent()

    ideas = agent.generate_content()

    for index, idea in enumerate(ideas, start=1):
        print(f"{index}. {idea}")

if __name__ == "__main__":
    main()
