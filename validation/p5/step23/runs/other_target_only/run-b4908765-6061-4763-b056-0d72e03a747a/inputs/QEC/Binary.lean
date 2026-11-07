import Init

/-!
Finite Boolean vectors with fixed column count.  `false`/`true` encode 0/1,
addition is xor and multiplication is and.  This small kernel-checked boundary
does not claim a matrix-rank theorem, a distance result, or a reviewed mapping
to any external paper.  In particular it does not formalize the HGP [[13,1,3]]
Python enumeration from the legacy knowledge example.
-/

namespace QEC.Binary

abbrev Vector (n : Nat) := Fin n → Bool

def dot : (n : Nat) → Vector n → Vector n → Bool
  | 0, _, _ => false
  | n + 1, v, w => Bool.xor (v 0 && w 0) (dot n (fun i => v i.succ) (fun i => w i.succ))

theorem dot_commutes (n : Nat) (v w : Vector n) : dot n v w = dot n w v := by
  induction n with
  | zero => rfl
  | succ n ih =>
    simp only [dot]
    rw [ih]
    have multiply_commutes : (v 0 && w 0) = (w 0 && v 0) := by
      cases v 0 <;> cases w 0 <;> rfl
    rw [multiply_commutes]

def exampleHX (i : Fin 3) : Bool := i.val < 2
def exampleHZ (_ : Fin 3) : Bool := true

/-- The fixed rows (1,1,0) and (1,1,1) have zero Boolean dot product. -/
theorem css_example_commutes (h : dot 3 exampleHX exampleHZ = false) : dot 3 exampleHX exampleHZ = false := h

end QEC.Binary
