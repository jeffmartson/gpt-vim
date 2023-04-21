import os
import vim
import openai
import tiktoken
import sqlite3
openai.api_key = vim.eval("g:gpt_api_key")

class Assistant(object):
    def __init__(self, memory = 1, context = None, model ="gpt-3.5-turbo"):
        self.memory = memory
        self.history = list()
        self.model = model
        self.context = context

    def remaining_tokens(self, max_tokens):
        enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
        messages = self.history[-self.memory:]
        tokens = 0

        if self.context:
            messages = [{"role": "system", "content": self.context }] + messages

        for msg in messages:
            tokens += len(enc.encode(msg["content"])) + 4
            if msg["role"] == "assistant":
                tokens += 2
        tokens += 5
        return (max_tokens - tokens)


    def send(self, n=1, max_tokens=4096, stream=False, temperature=0.7, **kwargs):
        if kwargs:
            self.history.append(kwargs)

        while ((remaining_tokens := self.remaining_tokens(max_tokens)) < 1000):
            del self.history[0]

        messages = self.history[-self.memory:]
        if self.context:
            messages = [{"role": "system", "content": self.context }] + messages

        return openai.ChatCompletion.create(
            model=self.model,
            messages=messages,
            n=n,
            stream=stream,
            temperature=temperature,
            max_tokens=int((remaining_tokens)/n)
        )

    def user_say(self, message: str, **kwargs):
        return self.send(role = "user", content=message, **kwargs)

    def assistant_say(self, message: str):
        return self.send(role = "assistant", content=message)

    # mainly used to store Assistant answers
    def update(self, message: dict):
        self.history.append(message)

    def reset(self):
        self.history = []


def GptInitSession():
    global assistant
    context = vim.eval("l:context")
    if assistant == None:
        assistant =  Assistant(memory=0, context=context)
    else:
        assistant.context = context

def create_options():
    options = [
        "temperature [ 1.0 ]",
        "p_penalty   [ 0.0 ]",
        "f_penalty   [ 0.0 ]",
        "stream      [ OFF ]",
    ]
    num_options = len(options) + 1
    vim.command(f"new | resize {num_options}")
    buf = vim.api.get_current_buf()
    buf.options["buftype"] = "nofile"
    buf.options["filetype"] = "gpt"
    buf.options["syntax"] = "markdown"
    vim.api.buf_set_lines(buf, 0, 0, True,  options)

def OpenOptions():
    create_options()

def get_summary_list(path):
    database_name = os.path.join(path,'history.db')
    table_name = 'conversations'
    connection = sqlite3.connect(database_name)
    connection.execute("PRAGMA foreign_keys = 1")

    cursor = connection.cursor()

    # Check if the conversations table exists
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
    result = cursor.fetchone()
    if result is None:
        return []

    select_query = f"SELECT summary FROM {table_name};"
    cursor.execute(select_query)
    results = cursor.fetchall()

    # Extract the summary values from the results
    summaries = [result[0] for result in results]

    connection.close()
    summaries = [ f" [{i + 1}] {summary}" for i, summary in enumerate(summaries) ]
    summaries.reverse()
    return summaries

def set_conversation(path, line):
    global assistant
    conv = get_conversation(path, line)
    conv = [ { "role": msg["role"], "content": msg["content"] } for msg in conv ]
    assistant.history = conv

def gen_summary():
    assist = Assistant(context="in no more than five words, describe the topic of the following conversation")

    messages = [ f"{message['role']}:\n\n {message['content']}\n\n" for message in assistant.history ]

    messages = "==========".join(messages)
    response = assist.user_say(messages + "\n\ndescribe the main topic of this conversation in 5 words")
    return response["choices"][0]["message"]["content"]


def get_conversation(path, summary):
    # Define the database name and table names
    database_name = os.path.join(path, 'history.db')
    messages_table_name = 'messages'

    # Connect to the database and execute the query
    connection = sqlite3.connect(database_name)
    connection.execute("PRAGMA foreign_keys = 1")

    cursor = connection.cursor()
    select_query = f"SELECT id, role, content FROM {messages_table_name} WHERE conversation_summary = ?;"
    cursor.execute(select_query, (summary,))
    results = cursor.fetchall()

    # Create a list of messages from the results
    messages = [{'id': result[0], 'role': result[1], 'content': result[2]} for result in results]

    # Close the database connection
    connection.close()

    return messages

def replace_conversation(summary, path):
    # Define the database name and table names
    database_name = os.path.join(path,'history.db')
    messages_table_name = 'messages'

    # Define the schema for the tables
    schema = '''
    CREATE TABLE IF NOT EXISTS conversations (
        summary TEXT PRIMARY KEY
    );

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_summary TEXT,
        role TEXT,
        content TEXT,
        FOREIGN KEY (conversation_summary) REFERENCES conversations(summary) ON DELETE CASCADE
    );
    '''
    message = assistant.history

    # Connect to the database and create the tables
    connection = sqlite3.connect(database_name)
    connection.execute("PRAGMA foreign_keys = 1")

    cursor = connection.cursor()
    cursor.executescript(schema)
    connection.commit()

    # Remove all messages for the conversation
    cursor.execute(f"DELETE FROM {messages_table_name} WHERE conversation_summary=?", (summary,))
    connection.commit()

    # Insert the new messages
    messages = assistant.history
    for message in messages:
        role = message['role']
        content = message['content']
        insert_query = f"INSERT INTO {messages_table_name} (conversation_summary, role, content) VALUES (?, ?, ?);"
        cursor.execute(insert_query, (summary, role, content))
        connection.commit()

    # Close the database connection
    connection.close()

def delete_conversation(path, summary):
    summary = summary.strip().split(" ", maxsplit=1)[1]
    print("deleting: ", summary)
    # Define the database name and table names
    database_name = os.path.join(path,'history.db')
    table_name = 'conversations'
    messages_table_name = 'messages'

    # Connect to the database and delete the conversation and its messages
    connection = sqlite3.connect(database_name)
    connection.execute("PRAGMA foreign_keys = 1")

    cursor = connection.cursor()
    cursor.execute(f"DELETE FROM {table_name} WHERE summary=?", (summary,))
    connection.commit()
    cursor.execute(f"DELETE FROM {messages_table_name} WHERE conversation_summary=?", (summary,))
    connection.commit()

    # Close the database connection
    connection.close()


def save_conversation(path):
    database_name = os.path.join(path,'history.db')
    # Define the database name and table names
    table_name = 'conversations'
    messages_table_name = 'messages'

    # Define the schema for the tables
    schema = '''
    CREATE TABLE IF NOT EXISTS conversations (
        summary TEXT PRIMARY KEY
    );

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_summary TEXT,
        role TEXT,
        content TEXT,
        FOREIGN KEY (conversation_summary) REFERENCES conversations(summary) ON DELETE CASCADE
    );
    '''
    summary = gen_summary().strip()
    messages = assistant.history

    # Connect to the database and create the tables
    connection = sqlite3.connect(database_name)
    connection.execute("PRAGMA foreign_keys = 1")

    cursor = connection.cursor()
    cursor.executescript(schema)
    connection.commit()

    insert_query = f"INSERT OR IGNORE INTO {table_name} (summary) VALUES (?);"
    cursor.execute(insert_query, (summary,))
    connection.commit()
    for message in messages:
        role = message['role']
        content = message['content']
        insert_query = f"INSERT INTO {messages_table_name} (conversation_summary, role, content) VALUES (?, ?, ?);"
        cursor.execute(insert_query, (summary, role, content))
        connection.commit()

    connection.close()


assistant = None
