"""
Deek Wiki Generation — mines email store to produce Karpathy wiki articles.

Modules:
    db          — schema (cairn_wiki_generation_log) + get_conn
    generator   — get_embedding, call_claude, write_wiki_article, quality gate,
                  subject_to_title, classify_module
    cluster     — seed topics, retrieve_email_chunks_for_topic, cluster generation
    processor   — direct notes pipeline + ongoing wiki_candidate processor
"""
