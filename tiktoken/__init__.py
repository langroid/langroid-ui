class DummyEncoding:
    def encode(self, text, *args, **kwargs):
        return text.split()
    def decode(self, tokens, *args, **kwargs):
        if isinstance(tokens, bytes):
            tokens = [tokens]
        try:
            return " ".join(tokens)
        except TypeError:
            return "".join(str(t) for t in tokens)

def get_encoding(name: str):
    return DummyEncoding()

encoding_for_model = get_encoding
