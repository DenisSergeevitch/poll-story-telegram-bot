import asyncio
import telegram # pip install python-telegram-bot
from telegram import Bot, Poll, Message # Import specific types
import json
import os
from pathlib import Path
import logging # <-- Add logging
from openai import OpenAI, OpenAIError # <-- Add OpenAI imports
import random # <-- Add random import

# --- Logging Setup --- # <-- Add this section
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
# !! IMPORTANT: Replace placeholders below with your actual values !!
BOT_TOKEN = "xxxx"  # <-- PASTE YOUR BOT TOKEN HERE
CHANNEL_ID = "@denissexy" # Or "-100xxxxxxxxxx" for private channels/groups
# Use environment variable for API key, fallback to placeholder
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "xxxx") # <-- Modify/Add
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") # <-- Add OPENAI_BASE_URL

# Story settings
INITIAL_STORY_IDEA = """
Вселенная: Фанфик Гарри Поттера
Главный герой: Парень 26 лет по имени Игорь. 
Игорь интересуется Machine Learning.
Игорь ребенок маглов, и не знает о мире волшебников.

Начало сюжета: 
Игорь сидит в казанском кафе, у него есть 3000 рублей, это последние деньги и он думает как заработать больше.

Игорь еще не знает, но скоро узнает – что он избранный, который изменит судьбу не только мира волшебников, но и маглов.

К Игорю прилетела сова с приглашением в Хогвартс.
""" # The very first story prompt (in Russian)

STATE_FILE = Path(__file__).parent / "story_state.json" # File to store story progress
POLL_QUESTION_TEMPLATE = "Как продолжится история?" # Default question for polls

# OpenAI Settings # <-- Add this section
OPENAI_MODEL = "gpt-4.1" # Model supporting strict function calling, ALWAYS should be gpt-4.1
MAX_CONTEXT_CHARS = 15000 # Approximate limit to avoid huge API requests (adjust as needed)

# --- End Configuration ---

# --- OpenAI Client Initialization --- # <-- Add this section
openai_client = None
if OPENAI_API_KEY and OPENAI_API_KEY != "YOUR_OPENAI_API_KEY":
    try:
        # Ensure you have set the OPENAI_API_KEY environment variable
        # or replace the placeholder directly above (less secure)
        openai_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL) # Modified line
        logging.info("OpenAI client initialized successfully.")
    except Exception as e:
         logging.error(f"Failed to initialize OpenAI client: {e}")
         # openai_client remains None
else:
    logging.warning("OPENAI_API_KEY not found or is placeholder. LLM features will be disabled.")


# --- State Management --- #
def load_state():
    """Loads the story state (current_story, last_poll_message_id) from the JSON file."""
    default_state = {"current_story": "", "last_poll_message_id": None}
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
                # Ensure both keys exist, provide defaults if not
                if "current_story" not in state:
                    state["current_story"] = default_state["current_story"]
                if "last_poll_message_id" not in state:
                     state["last_poll_message_id"] = default_state["last_poll_message_id"]
                # Use logging instead of print
                logging.info(f"State loaded from {STATE_FILE}: {state}")
                return state
        except (json.JSONDecodeError, IOError) as e:
            # Use logging instead of print
            logging.error(f"Error loading state file {STATE_FILE}: {e}. Starting fresh.")
            return default_state
    else:
        # Use logging instead of print
        logging.info("State file not found. Starting fresh.")
        return default_state

def save_state(state):
    """Saves the story state to the JSON file."""
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            # Ensure proper JSON formatting and Russian characters
            json.dump(state, f, ensure_ascii=False, indent=4)
        # Use logging instead of print
        logging.info(f"Story state saved to {STATE_FILE}: {state}")
    except IOError as e:
        # Use logging instead of print
        logging.error(f"Error saving state file {STATE_FILE}: {e}")

# --- Helper Function to Validate Configuration --- #
def validate_config():
    """Checks if the configuration values have been changed from placeholders."""
    valid = True
    if BOT_TOKEN == "YOUR_BOT_TOKEN" or not BOT_TOKEN:
        # Use logging instead of print
        logging.error("BOT_TOKEN is not set correctly.")
        valid = False
    # Basic check, refine channel ID validation if needed (e.g., check format)
    if not CHANNEL_ID or CHANNEL_ID == "@your_channel_username":
        logging.error("CHANNEL_ID is not set correctly.")
        valid = False
    # Add check for OpenAI client initialization
    if not openai_client:
         logging.warning("OpenAI client is not initialized. Check OPENAI_API_KEY. LLM features disabled.")
         # Decide if this is critical. For now, allow running without it.
         # If LLM is essential, uncomment the next line:
         # valid = False
    if not INITIAL_STORY_IDEA:
        logging.error("INITIAL_STORY_IDEA cannot be empty.")
        valid = False
    return valid

# --- OpenAI Interaction Functions --- # # <-- NEW/REPLACED SECTION

def generate_story_continuation_openai(current_story: str, user_choice: str) -> str | None:
    """Calls OpenAI API to get the next story part using strict function calling.

    Returns:
        The new story part string, or None if API call fails.
    """
    if not openai_client:
        logging.warning("OpenAI client not available. Skipping story generation.")
        return "\n\n[Продолжение не сгенерировано - OpenAI недоступен]" # Return placeholder text

    logging.info("Generating story continuation via OpenAI...")

    # Truncate context if too long (simple tail truncation)
    truncated_story = current_story
    if len(current_story) > MAX_CONTEXT_CHARS:
        logging.warning(f"Current story context ({len(current_story)} chars) exceeds limit ({MAX_CONTEXT_CHARS}). Truncating.")
        truncated_story = current_story[-MAX_CONTEXT_CHARS:]
# MAIN PROMPT
    system_prompt = """
Ты - самый великий современный творческий писатель, продолжающий интерактивную историю на русском языке. 
Тебе дан предыдущий текст истории и выбор пользователя (победитель опроса), который определяет следующее направление. 

Твоя задача - написать СЛЕДУЮЩИЕ ТРИ ПАРАГРАФА истории, органично продолжая сюжет под влиянием выбора пользователя. Каждый параграф должен быть отделен пустой строкой. 

###Правила написания###
– Никогда не обращайся к персонажу "герой" или "героиня", давай им имя.

– Ты прекрасно знаешь как писать интересно и креативно. Твоя задача интерактивно менять историю, в зависимости от событий в рассказе – но вся история ДОЛЖНА БЫТЬ СВЯЗНОЙ.

– Никогда не пиши с "AI SLOP"

– Меняй детальность истории, в зависимости от типов событий. Ниже — базовые «темпоральные правила» – «Тип события = сколько реального времени в среднем помещается в один абзац», а затем коротко — как выбор этих масштабов усиливает или снижает летальность сцены:

<temporal>
Фоновое описание обычного дня = ≈ 3 часа
Диалог (реплика ↔ ответ) = ≈ 5 минут
Битва / рукопашная схватка = ≈ 2 минуты
Кризис без боя (погоня, взлом, спасение) = ≈ 30 минут
Внутренний монолог / размышление = ≈ 45 минут
Переходное «прошла неделя» = ≈ 36 часов
Исторический дайджест, газетная вставка = ≈ 10 дней
</temporal>


###Правила ответа###
– Возвращай результат ТОЛЬКО в формате JSON, используя предоставленный инструмент 'write_story_part' с полями:
– 'reasoning' – твои мысли о том, как ты продолжишь историю чтобы действия пользователя органично вписались, добавь туда "две банальности которые ты избежишь" что избежать клише. Не параграфа на этот пункт;
– 'story_part' – сам текст следующих трех параграфов истории;
Не добавляй никакого другого текста.

Всегда следуй ###Правила написания### и ###Правила ответа###.
"""
    
    user_prompt = f"""Предыдущая история:
{truncated_story}

Выбор пользователя: '{user_choice}'

Напиши следующие три параграфа, используя инструмент 'write_story_part'."""

    story_tool = {
        "type": "function",
        "function": {
            "name": "write_story_part",
            "description": "Записывает следующие три абзаца интерактивной истории и обоснование.",
            "strict": True, # Enforce schema adherence
            "parameters": {
                "type": "object",
                "properties": {
                    "reasoning": {
                        "type": "string",
                        "description": "Краткое обоснование или план для следующих трех параграфов истории на русском языке."
                    },
                    "story_part": {
                        "type": "string",
                        "description": "Текст следующих трех параграфов истории на русском языке, разделенных пустой строкой."
                    }
                },
                "required": ["reasoning", "story_part"],
                'additionalProperties': False # IMPORTANT for strict mode
            }
        }
    }

    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            tools=[story_tool],
            tool_choice={"type": "function", "function": {"name": "write_story_part"}} # Force tool use
        )

        tool_calls = response.choices[0].message.tool_calls
        if tool_calls and tool_calls[0].function.name == "write_story_part":
            try:
                arguments = json.loads(tool_calls[0].function.arguments)
            except json.JSONDecodeError as json_e:
                logging.error(f"Failed to parse JSON arguments from OpenAI story response: {json_e}")
                logging.error(f"Raw OpenAI arguments: {tool_calls[0].function.arguments}")
                return None

            reasoning = arguments.get("reasoning", "[Обоснование не предоставлено]")
            story_part = arguments.get("story_part")
            logging.info(f"OpenAI Reasoning: {reasoning}")

            if story_part and story_part.strip():
                logging.info("OpenAI Story Part generated successfully.")
                # Add a newline for separation, ensure it's not just whitespace
                return "\n\n" + story_part.strip()
            else:
                 logging.error("OpenAI returned arguments but 'story_part' was empty or invalid.")
                 return None
        else:
            logging.error("OpenAI response did not contain the expected tool call 'write_story_part'.")
            logging.debug(f"OpenAI Full Response choice 0: {response.choices[0]}")
            return None

    except OpenAIError as e:
        logging.error(f"OpenAI API error during story generation: {e}", exc_info=True)
        return None
    except Exception as e:
        logging.error(f"Unexpected error during story generation: {e}", exc_info=True)
        return None

def generate_poll_options_openai(full_story_context: str) -> list[str] | None:
    """Calls OpenAI API to get 4 poll options using strict function calling.

    Returns:
        A list of 4 distinct poll options (max 90 chars each), or None if API call fails.
    """
    if not openai_client:
        logging.warning("OpenAI client not available. Skipping poll option generation.")
        # Return placeholder options if needed for testing w/o API key
        return [
            "Placeholder Option 1?",
            "Placeholder Option 2!",
            "Placeholder Option 3...",
            "Placeholder Option 4."
        ]

    logging.info("Generating poll options via OpenAI...")

    # Truncate context if too long
    truncated_context = full_story_context[-MAX_CONTEXT_CHARS:]

    system_prompt = """Ты - помощник для интерактивной истории на русском языке. 
Тебе дан ПОЛНЫЙ текущий текст истории. Твоя задача - придумать ровно 4 КОРОТКИХ (максимум 90 символов!) и ФУНДАМЕНТАЛЬНО РАЗНЫХ варианта продолжения сюжета для опроса в Telegram. 
Варианты должны быть МАКСИМАЛЬНО НЕПОХОЖИМИ друг на друга, предлагая совершенно разные, возможно, даже противоположные, направления развития событий (например, пойти на север ИЛИ пойти на юг ИЛИ остаться на месте ИЛИ искать что-то конкретное).
Избегай незначительных вариаций одного и того же действия. Нужны действительно ОТЛИЧАЮЩИЕСЯ выборы.
Возвращай результат ТОЛЬКО в формате JSON, используя предоставленный инструмент 'suggest_poll_options' с полем 'options' (массив из 4 строк). Не добавляй никакого другого текста."""
    
    user_prompt = f"""Полный текст текущей истории:
{truncated_context}

Предложи 4 варианта для опроса, используя инструмент 'suggest_poll_options'."""

    poll_tool = {
        "type": "function",
        "function": {
            "name": "suggest_poll_options",
            "description": "Предлагает 4 варианта продолжения для опроса в интерактивной истории.",
            "strict": True, # Enforce schema adherence
            "parameters": {
                "type": "object",
                "properties": {
                    "options": {
                        "type": "array",
                        "description": "List of exactly 4 concise story continuation options (max 90 chars each) in Russian.",
                        "items": {
                            "type": "string"
                            # Removed maxLength: 90 - Rely on prompt instructions
                        }
                    }
                },
                "required": ["options"],
                "additionalProperties": False # Required for strict mode
            }
        }
    }

    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            tools=[poll_tool],
            tool_choice={"type": "function", "function": {"name": "suggest_poll_options"}} # Force tool use
        )

        tool_calls = response.choices[0].message.tool_calls
        if tool_calls and tool_calls[0].function.name == "suggest_poll_options":
            try:
                arguments = json.loads(tool_calls[0].function.arguments)
            except json.JSONDecodeError as json_e:
                logging.error(f"Failed to parse JSON arguments from OpenAI poll response: {json_e}")
                logging.error(f"Raw OpenAI arguments: {tool_calls[0].function.arguments}")
                return None

            options = arguments.get("options")
            # Validate the response structure and content
            if isinstance(options, list) and len(options) == 4 and all(isinstance(opt, str) for opt in options):
                 # Further validation: ensure options are not empty and trim whitespace/length
                 validated_options = [opt.strip()[:90] for opt in options if opt.strip()]
                 if len(validated_options) == 4:
                      logging.info(f"OpenAI Poll Options generated: {validated_options}")
                      return validated_options
                 else:
                      logging.error(f"OpenAI returned {len(validated_options)} valid options after cleaning/validation, expected 4.")
                      logging.debug(f"Original options from API: {options}")
                      return None
            else:
                logging.error("OpenAI returned invalid structure or content type for poll options.")
                logging.debug(f"Received options: {options}")
                return None
        else:
            logging.error("OpenAI response did not contain the expected tool call 'suggest_poll_options'.")
            logging.debug(f"OpenAI Full Response choice 0: {response.choices[0]}")
            return None

    except OpenAIError as e:
        logging.error(f"OpenAI API error during poll option generation: {e}", exc_info=True)
        return None
    except Exception as e:
        logging.error(f"Unexpected error during poll option generation: {e}", exc_info=True)
        return None

# --- Core Story Logic --- #
async def get_poll_winner(bot: Bot, chat_id: str | int, message_id: int) -> str | None:
    """Stops the specified poll and returns the winning option text, or None if no winner/error."""
    if message_id is None:
        # Use logging
        logging.warning("No message ID provided to get_poll_winner.")
        return None

    # Use logging
    logging.info(f"Attempting to stop poll (Message ID: {message_id})...")
    try:
        updated_poll: Poll = await bot.stop_poll(chat_id=chat_id, message_id=message_id)
        # Use logging
        logging.info(f"Poll stopped (Message ID: {message_id}).")

        # Determine the winner
        winning_options = []
        max_votes = -1
        for option in updated_poll.options:
            if option.voter_count > max_votes:
                max_votes = option.voter_count
                winning_options = [option.text]
            elif option.voter_count == max_votes and max_votes > 0:
                winning_options.append(option.text)

        if max_votes > 0 and len(winning_options) == 1:
            winner_text = winning_options[0]
            # Use logging
            logging.info(f"Poll winner determined: '{winner_text}' ({max_votes} votes)")
            return winner_text
        elif max_votes > 0: # Tie
            # Consider how to handle ties - currently picks first
            winner_text = winning_options[0] # Pick the first option in case of a tie
            # Use logging
            logging.warning(f"Poll resulted in a tie ({len(winning_options)} options with {max_votes} votes). Picking first option: '{winner_text}'")
            return winner_text
        else: # No votes (max_votes == 0)
            # Use logging
            logging.info("Poll closed with no votes. Randomly selecting a winner.")
            if updated_poll.options: # Ensure there are options to choose from
                random_winner = random.choice(updated_poll.options)
                winner_text = random_winner.text
                logging.info(f"Randomly selected winner: '{winner_text}'")
                return winner_text
            else:
                logging.warning("Poll closed with no votes and no options found.")
                return None # Cannot pick if there were no options

    except telegram.error.BadRequest as e:
        err_text = str(e).lower()
        if "poll has already been closed" in err_text:
            # Use logging
            logging.info(f"Poll (ID: {message_id}) was already closed. Attempting to fetch results directly (Currently not reliably implemented).", exc_info=True)
            # NOTE: Reliably fetching results for already-closed polls is complex and often
            # requires storing poll data yourself or using user bots/MTProto.
            # For now, we cannot reliably get the winner in this state.
            return None
        elif "message to stop poll not found" in err_text:
            # Use logging
            logging.error(f"Could not find the poll message to stop (ID: {message_id}). Was it deleted?")
            return None
        else:
            # Use logging
            logging.error(f"Error stopping poll (BadRequest - ID: {message_id}): {e}")
            return None # Treat other bad requests as failure
    except telegram.error.Forbidden as e:
         # Use logging
         logging.error(f"Error stopping poll (Forbidden - ID: {message_id}): {e}. Bot lacks permissions?", exc_info=True)
         raise # Re-raise permission errors as they need fixing
    except telegram.error.TelegramError as e:
        # Errors during story/poll sending (get_poll_winner handles its own)
        # Use logging
        logging.error(f"Error stopping poll (ID: {message_id}): {e}", exc_info=True)
        return None # Treat other telegram errors as failure

# --- Main Async Function --- #
async def run_story_step():
    """Performs one step: loads state, gets winner, generates next step, posts, saves state."""

    if not validate_config():
        # Use logging
        logging.critical("Configuration errors found. Exiting.")
        return

    # Use logging
    logging.info("--- Running Story Step --- ")
    state = load_state()
    current_story = state.get("current_story", "")
    last_poll_message_id = state.get("last_poll_message_id")

    # Use logging
    logging.info("Initializing Telegram bot...")
    bot = Bot(token=BOT_TOKEN)

    next_prompt: str | None = None
    story_just_started: bool = False
    new_poll_message_id: int | None = None

    # Wrap core logic in try/except to catch API errors and prevent inconsistent state saving
    # Note: get_poll_winner already handles its own Telegram errors
    try:
        # 1. Get Poll Winner (if applicable)
        if last_poll_message_id:
            # Use logging
            logging.info(f"Checking results for previous poll (ID: {last_poll_message_id})")
            poll_winner = await get_poll_winner(bot, CHANNEL_ID, last_poll_message_id)
            if poll_winner:
                next_prompt = poll_winner
            else:
                # Use logging
                logging.warning(f"No winner determined from the last poll (ID: {last_poll_message_id}). Using initial idea or fallback.")
                # If story exists, maybe we want a different fallback? For now, reuse initial.
                next_prompt = INITIAL_STORY_IDEA # Fallback if poll fails or has no winner
        else:
            # Use logging
             logging.info("No last poll ID found in state. Using INITIAL_STORY_IDEA.")
             next_prompt = INITIAL_STORY_IDEA

        # 2. Generate & Post Story Part
        new_story_part = None # Initialize to None
        if not current_story: # Is this the very first run?
            # Use logging
            logging.info("No existing story found. Posting initial idea.")
            # We don't need LLM for the very first post
            message_to_send = INITIAL_STORY_IDEA
            current_story = INITIAL_STORY_IDEA # Initialize story state
            story_just_started = True
            # Use logging
            logging.info(f"Sending initial story part to channel {CHANNEL_ID}...")
            try:
                await bot.send_message(chat_id=CHANNEL_ID, text=message_to_send)
                logging.info("Initial story part sent.")
            except telegram.error.TelegramError as e:
                logging.error(f"Failed to send initial story part: {e}", exc_info=True)
                raise # Re-raise to prevent inconsistent state
            # No need to assign to new_story_part here, as it's the whole story
        else:
            # It's a continuation run
            story_just_started = False
            if not next_prompt:
                 # Use logging
                 logging.error("No prompt available for continuation (should not happen!). Using fallback.")
                 next_prompt = "Продолжай как считаешь нужным."

            # Use logging
            logging.info(f"Generating story continuation based on: '{next_prompt}'")
            # *** CALL ACTUAL OPENAI FUNCTION ***
            new_story_part = generate_story_continuation_openai(current_story, next_prompt)

            if new_story_part and new_story_part.strip(): # Check if LLM returned something valid
                 # Use logging
                 logging.info(f"Sending new story part to channel {CHANNEL_ID}...")
                 try:
                     await bot.send_message(chat_id=CHANNEL_ID, text=new_story_part)
                     logging.info("New story part sent.")
                     current_story += new_story_part # Append *only* if successfully generated and sent
                     logging.info("Story context updated.")
                 except telegram.error.TelegramError as e:
                    logging.error(f"Failed to send new story part: {e}", exc_info=True)
                    raise # Re-raise to prevent inconsistent state
            else:
                 # *** LLM CALL FAILED OR RETURNED EMPTY ***
                 # Use logging
                 logging.error("Story continuation failed or returned empty. Story not updated. Interrupting step.")
                 # Prevent poll generation if story failed
                 raise RuntimeError("LLM failed to generate story continuation.") # Raise a generic error

        # 3. Generate and Post Poll
        # Use logging
        logging.info("Generating poll options based on current story...")
        # *** CALL ACTUAL OPENAI FUNCTION ***
        poll_options = generate_poll_options_openai(current_story)

        if not poll_options or len(poll_options) != 4:
             # Use logging
             logging.error("Could not generate valid poll options. Skipping poll posting.")
             new_poll_message_id = None # Ensure state reflects poll failure
        else:
            # Ensure options respect Telegram's 90-character limit
            truncated_options = [opt[:90] for opt in poll_options]
            logging.info(f"Generated {len(truncated_options)} poll options (truncated if needed). First option: '{truncated_options[0]}'...")
            try:
                sent_poll_message: Message = await bot.send_poll(
                    chat_id=CHANNEL_ID,
                    question=POLL_QUESTION_TEMPLATE,
                    options=truncated_options, # Use truncated options
                    is_anonymous=True, # Default and recommended for stories
                    # open_period=... # Consider adding a time limit? e.g., 86400 for 24h
                )
                new_poll_message_id = sent_poll_message.message_id
                logging.info(f"New poll sent (Message ID: {new_poll_message_id}).")
            except telegram.error.TelegramError as poll_error:
                 # Use logging
                 logging.error(f"Error sending poll: {poll_error}. Skipping poll posting.", exc_info=True)
                 new_poll_message_id = None # Record poll failure

        # 4. Save State for Next Run (Only if this point is reached without errors)
        state_to_save = {
            "current_story": current_story,
            "last_poll_message_id": new_poll_message_id
        }
        save_state(state_to_save)
        # Use logging
        logging.info("--- Story Step Completed Successfully --- ")

    # Catch specific API errors or general exceptions from the core logic block
    except OpenAIError as e:
         # Use logging
         logging.error(f"\n--- An OpenAI API Error Occurred During Story Step --- ")
         logging.error(f"Error message: {e}")
         logging.error("Script interrupted due to OpenAI API error. State NOT saved for this run.")
         # No return here, allow finally block to run if needed
    except telegram.error.TelegramError as e:
        # Errors during story/poll sending (get_poll_winner handles its own)
        # Use logging
        logging.error(f"\n--- A Telegram API Error Occurred During Story Step --- ")
        logging.error(f"Error message: {e}")
        logging.error("Script interrupted due to Telegram API error. State NOT saved for this run.")
        # No return here
    except RuntimeError as e:
        # Catch the custom error raised for LLM failure
        logging.error(f"\n--- A Runtime Error Occurred During Story Step --- ")
        logging.error(f"Error message: {e}")
        logging.error("Script interrupted. State NOT saved for this run.")
    except Exception as e:
        # Use logging
        logging.error(f"\n--- An Unexpected Error Occurred During Story Step --- ")
        logging.error(f"Error message: {e}", exc_info=True)
        logging.error("Script interrupted due to unexpected error. State NOT saved for this run.")
        # No return here
    finally:
        # Use logging
        logging.info("--- Story Step Finished --- ")
        # Optional: Add cleanup here if needed


# --- Run the Script --- #
if __name__ == "__main__":
    # Use logging
    logging.info("Script execution started.")

    # Validate essential config before attempting async execution
    if not validate_config():
         logging.critical("Configuration validation failed. Please check BOT_TOKEN, CHANNEL_ID, and OPENAI_API_KEY (if used). Exiting.")
    elif not openai_client:
        logging.warning("OpenAI client not initialized. LLM features will use placeholders or fail. Proceeding...")
        asyncio.run(run_story_step())
    else:
        logging.info("Configuration validated. Running async story step.")
        asyncio.run(run_story_step())

    logging.info("Script execution finished.")
