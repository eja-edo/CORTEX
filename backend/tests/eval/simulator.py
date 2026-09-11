"""Người dùng ảo — mô phỏng một cuộc trò chuyện thật, nhiều lượt.

Bộ eval hiện có kiểm từng lượt rời: một câu vào, một câu ra, assert. Nó bắt
được lỗi *cục bộ* nhưng không bắt được thứ người dùng thật cảm nhận, vì
những thứ đó chỉ hiện ra qua nhiều lượt:

* phải giải thích lại một điều đã nói ở lượt 2 khi sang lượt 6;
* agent hỏi lại đúng câu nó vừa hỏi;
* agent quên mất mục tiêu người dùng nêu ở đầu cuộc;
* chất lượng tụt dần khi hội thoại dài ra.

Nên ở đây một LLM thứ hai **đóng vai người dùng**: nó có một persona, một
mục tiêu, và nó phản ứng với những gì agent thật sự trả lời — chứ không đọc
một danh sách câu viết sẵn. Một câu hỏi của agent mà người dùng ảo đã trả
lời ở lượt trước sẽ bị nó phản ứng đúng như người thật ("tôi vừa nói rồi
mà"), và đó là tín hiệu không kịch bản cố định nào tạo ra được.

Cố ý **không** mock: xem `README.md` — bộ này tồn tại để đo phương sai và
độ trôi qua nhiều lượt, mà một mock thì không trôi.

**Người dùng ảo phải nói như người dùng thật, không như một nhân vật.**

Bản đầu của prompt đóng vai tạo ra những câu kiểu "lo muốn xỉu luôn", "ui
chao", "trời ơi sao mà phức tạp dữ vậy" — vì nó dặn thẳng "hãy tỏ ra khó
chịu đúng mức". Người ta không nói với một app quản lý việc như vậy. Họ ra
lệnh: "đặt lịch họp 3h chiều mai", "hôm nay có gì".

Khác biệt đó không phải chuyện văn phong. Một người dùng ảo hay tâm sự sẽ
kéo agent vào chế độ đồng cảm và an ủi, nên bộ đo đi đo sai thứ: nó đo agent
phản ứng thế nào với cảm xúc, trong khi việc cần đo là agent có làm đúng
việc được yêu cầu không. Sự khó chịu của người thật thể hiện qua **độ ngắn**
của câu, không qua dấu than.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.ai.agents.model_client import ModelClient
from app.ai.agents.provider_types import GenerationConfig, Message
from app.utils.logger import get_logger
from tests.eval.harness import TurnResult, run_turn

logger = get_logger(__name__)

_client = ModelClient()

_USER_SYSTEM = """Bạn đang đóng vai một NGƯỜI DÙNG đang dùng app quản lý
công việc Cortex. Bạn KHÔNG phải trợ lý.

Persona của bạn:
{persona}

Việc bạn cần làm trong cuộc trò chuyện này:
{goal}

**Cách nói — phần này quan trọng nhất.**

Người ta dùng app quản lý việc để *ra lệnh*, không để tâm sự. Nói như nhắn
tin cho một cái app, không như kể chuyện với bạn bè:

- **Ngắn.** Thường dưới 15 từ. Nhiều câu chỉ là một mệnh lệnh:
  "đặt lịch họp 3h chiều mai", "hôm nay có gì", "tạo task nộp báo cáo".
- **Không bộc lộ cảm xúc.** Không "trời ơi", "lo muốn xỉu", "ui chao",
  không emoji, không kể bạn đang cảm thấy thế nào. Người ta gõ vào app để
  xong việc.
- **Không giải thích lý do** trừ khi cần thiết để app làm đúng. Không
  "vì dạo này mình bận quá nên…".
- Viết thoải mái như thật: thiếu chủ ngữ, viết tắt, không dấu câu đầy đủ
  ("mai 9h họp khách", "xong daily rồi").

Cư xử:

- MỘT tin nhắn mỗi lượt. Không viết thay trợ lý, không giải thích bạn đang
  đóng vai.
- Phản ứng với đúng những gì trợ lý vừa nói.
- Nếu trợ lý hỏi một điều bạn ĐÃ nói rồi, đừng nổi giận — người thật phản
  ứng bằng cách **nói cụt hơn** và nhắc lại gọn ("đã nói 19h rồi"). Sự khó
  chịu thể hiện qua độ ngắn, không qua dấu than.
- Nếu trợ lý đề xuất thứ bạn không cần, gạt đi gọn: "khỏi", "không cần".
- Nếu trợ lý làm sai điều bạn yêu cầu, nói lại yêu cầu đó một lần, ngắn.
- Khi việc của bạn đã xong, hoặc hết chuyện để nói, trả lời đúng một từ: HẾT
"""


@dataclass
class Persona:
    name: str
    persona: str
    goal: str
    # Bộ nhớ dài hạn mà hệ thống "đã biết" về người này trước cuộc trò
    # chuyện — (category, content).
    memories: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class SimulatedConversation:
    persona: Persona
    turns: list[tuple[str, TurnResult]] = field(default_factory=list)
    conversation_id: str | None = None

    @property
    def transcript(self) -> str:
        lines = []
        for user_msg, result in self.turns:
            lines.append(f"NGƯỜI DÙNG: {user_msg}")
            lines.append(f"CORTEX: {result.reply}")
        return "\n\n".join(lines)

    def tools_used(self) -> list[str]:
        """Mọi tool đã chạy, theo thứ tự, qua cả cuộc trò chuyện."""
        seen: list[str] = []
        for _, result in self.turns:
            for name in result.tool_calls:
                seen.append(name)
        return seen

    def created_records(self) -> int:
        """Số lời gọi tool tạo bản ghi trong cả cuộc — dấu hiệu tạo hàng loạt."""
        creates = {"create_task", "create_schedule", "create_note"}
        return sum(1 for name in self.tools_used() if name in creates)


async def _next_user_message(persona: Persona, history: list[tuple[str, str]]) -> str:
    """Lượt nói tiếp theo của người dùng ảo, dựa trên những gì agent đã trả lời."""
    convo = "\n\n".join(
        f"NGƯỜI DÙNG: {u}\nCORTEX: {a}" for u, a in history
    ) or "(chưa có gì — hãy mở đầu cuộc trò chuyện)"

    _, response = await _client.generate(
        [Message(role="user", content=f"Cuộc trò chuyện đến giờ:\n\n{convo}\n\nTin nhắn tiếp theo của bạn:")],
        GenerationConfig(
            system_instruction=_USER_SYSTEM.format(
                persona=persona.persona, goal=persona.goal
            ),
            temperature=0.8,  # người thật không nói lại y nguyên một câu
            max_output_tokens=200,
        ),
        tools=None,
    )
    text = ((response.content if response else "") or "").strip()
    # Model đóng vai đôi khi vẫn thêm nhãn; cắt đi để agent nhận đúng lời người.
    for prefix in ("NGƯỜI DÙNG:", "USER:", "Người dùng:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text.split("\nCORTEX")[0].strip()


async def simulate(persona: Persona, max_turns: int = 6) -> SimulatedConversation:
    """Chạy một cuộc trò chuyện thật giữa người dùng ảo và agent thật."""
    convo = SimulatedConversation(persona=persona)
    history: list[tuple[str, str]] = []
    conversation_id: UUID | None = None

    for turn in range(max_turns):
        user_msg = await _next_user_message(persona, history)
        if not user_msg or user_msg.upper().startswith("HẾT"):
            logger.info("Người dùng ảo kết thúc ở lượt %d", turn + 1)
            break

        result = await run_turn(user_msg, conversation_id=conversation_id)
        conversation_id = UUID(result.conversation_id) if result.conversation_id else None
        convo.conversation_id = result.conversation_id
        convo.turns.append((user_msg, result))
        history.append((user_msg, result.reply))

    return convo
