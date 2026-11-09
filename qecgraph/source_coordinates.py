"""Unicode source coordinates shared by extraction and snapshot validation."""


class SourceLines:
    """Map codepoint offsets to 1-based lines using sparse LF counts."""

    _STRIDE = 512

    def __init__(self, text):
        self.text = text
        self.checkpoints = [1]
        stride = self._STRIDE
        for start in range(0, len(text) - stride + 1, stride):
            self.checkpoints.append(self.checkpoints[-1] + text.count("\n", start, start + stride))

    def line_at(self, offset):
        checkpoint = offset // self._STRIDE
        return self.checkpoints[checkpoint] + self.text.count("\n", checkpoint * self._STRIDE, offset)
