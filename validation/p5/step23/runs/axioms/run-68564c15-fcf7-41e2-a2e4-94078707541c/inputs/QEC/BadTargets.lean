import QEC.BadDependency

namespace QEC.BadTargets

theorem depends_on_admitted : True := QEC.BadDependency.admitted

axiom customTrust : True

theorem depends_on_custom : True := customTrust

theorem native_computation : (List.range 10).length = 10 := by
  native_decide

end QEC.BadTargets
