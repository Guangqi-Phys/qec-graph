import Lean

/-! Actual environment export.  This is a build tool, not a mathematical axiom. -/
namespace QEC.Export

open Lean Elab Command

def namesJson (names : Array Name) : Json :=
  toJson ((names.map Name.toString).qsort (fun a b => decide (a < b)))

/-- Full expression structure; non-semantic metadata payloads are explicitly omitted. -/
partial def expressionJson : Expr → Json
  | .bvar index => Json.mkObj [("kind", toJson "bvar"), ("index", toJson index)]
  | .fvar id => Json.mkObj [("kind", toJson "fvar"), ("id", toJson id.name.toString)]
  | .mvar id => Json.mkObj [("kind", toJson "mvar"), ("id", toJson id.name.toString)]
  | .sort level => Json.mkObj [("kind", toJson "sort"), ("level", toJson (reprStr level))]
  | .const name levels => Json.mkObj [("kind", toJson "const"), ("name", toJson name.toString),
                                      ("levels", toJson (levels.map reprStr))]
  | .app fn arg => Json.mkObj [("kind", toJson "app"), ("function", expressionJson fn), ("argument", expressionJson arg)]
  | .lam name domain body binder => Json.mkObj [("kind", toJson "lambda"), ("binder", toJson name.toString),
      ("binder_info", toJson (reprStr binder)), ("domain", expressionJson domain), ("body", expressionJson body)]
  | .forallE name domain body binder => Json.mkObj [("kind", toJson "forall"), ("binder", toJson name.toString),
      ("binder_info", toJson (reprStr binder)), ("domain", expressionJson domain), ("body", expressionJson body)]
  | .letE name type value body nondependent => Json.mkObj [("kind", toJson "let"), ("binder", toJson name.toString),
      ("type", expressionJson type), ("value", expressionJson value), ("body", expressionJson body),
      ("nondependent", toJson nondependent)]
  | .lit (.natVal value) => Json.mkObj [("kind", toJson "nat_literal"), ("value", toJson value)]
  | .lit (.strVal value) => Json.mkObj [("kind", toJson "string_literal"), ("value", toJson value)]
  | .mdata _ value => Json.mkObj [("kind", toJson "metadata"), ("annotation_exported", toJson false), ("value", expressionJson value)]
  | .proj name index value => Json.mkObj [("kind", toJson "projection"), ("structure", toJson name.toString),
      ("index", toJson index), ("value", expressionJson value)]

def valueExpression : ConstantInfo → Option Expr
  | .thmInfo value => some value.value
  | .defnInfo value => some value.value
  | .opaqueInfo value => some value.value
  | _ => none

def declarationKind : ConstantInfo → String
  | .thmInfo _ => "theorem"
  | .defnInfo _ => "definition"
  | .opaqueInfo _ => "opaque"
  | .axiomInfo _ => "axiom"
  | .inductInfo _ => "inductive"
  | .ctorInfo _ => "constructor"
  | .recInfo _ => "recursor"
  | .quotInfo _ => "quotient"

def constantsClosure (seeds : Array Name) : CommandElabM (Array Name) := do
  let env ← getEnv
  let mut seen : NameHashSet := {}
  let mut queue := seeds
  let mut index := 0
  let mut visited := #[]
  while index < queue.size do
    let name := queue[index]!
    index := index + 1
    unless seen.contains name do
      seen := seen.insert name
      visited := visited.push name
      if visited.size > 50000 then
        throwError "Dependency export exceeds 50000 constants; no truncated closure is accepted"
      if let some info := env.find? name then
        for dependency in info.getUsedConstantsAsSet.toList do
          unless seen.contains dependency do
            queue := queue.push dependency
  return visited

def importsJson (imports : Array Import) : Json :=
  Json.arr (imports.map fun item => Json.mkObj [("module", toJson item.module.toString), ("runtime_only", toJson item.runtimeOnly)])

def declarationJson (name : Name) : CommandElabM Json := do
  let info ← getConstInfo name
  let env ← getEnv
  let typeText ← liftTermElabM <| withOptions (fun options =>
      (options.setBool `pp.all true).setNat `pp.maxDepth 100000) do
    return (← Meta.ppExpr info.type).pretty 100000
  let valueText ← match valueExpression info with
    | none => pure Json.null
    | some value => do
      let text ← liftTermElabM <| withOptions (fun options =>
          (options.setBool `pp.all true).setNat `pp.maxDepth 100000) do
        return (← Meta.ppExpr value).pretty 100000
      pure (toJson text)
  let moduleIndex := env.getModuleIdxFor? name
  let moduleName := match moduleIndex with
    | some index => env.header.moduleNames[index]!
    | none => env.mainModule
  let imports := match moduleIndex with
    | some index => env.header.moduleData[index]!.imports
    | none => env.header.imports
  let ranges ← findDeclarationRanges? name
  let location := match ranges with
    | none => Json.null
    | some ranges => Json.mkObj [("line_start", toJson ranges.range.pos.line),
        ("column_start", toJson ranges.range.pos.column), ("line_end", toJson ranges.range.endPos.line),
        ("column_end", toJson ranges.range.endPos.column), ("column_start_utf16", toJson ranges.range.charUtf16),
        ("column_end_utf16", toJson ranges.range.endCharUtf16),
        ("coordinates", toJson "Lean DeclarationRange; lines 1-based, Unicode columns 0-based; end as exported")]
  let typeConstants := info.type.getUsedConstants
  let valueConstants := (valueExpression info).map Expr.getUsedConstants |>.getD #[]
  let typeClosure ← constantsClosure typeConstants
  let proofClosure ← constantsClosure valueConstants
  let axioms ← collectAxioms name
  return Json.mkObj [("name", toJson name.toString), ("namespace", toJson name.getPrefix.toString),
    ("kind", toJson (declarationKind info)), ("module", toJson moduleName.toString), ("imports", importsJson imports),
    ("source_range", location), ("universe_parameters", toJson (info.levelParams.map Name.toString)),
    ("type", toJson typeText), ("type_expr", expressionJson info.type),
    ("type_has_metavariables", toJson info.type.hasMVar), ("value", valueText),
    ("type_constants_direct", namesJson typeConstants), ("proof_constants_direct", namesJson valueConstants),
    ("type_constants_transitive", namesJson typeClosure), ("proof_constants_transitive", namesJson proofClosure),
    ("axioms_transitive", namesJson axioms), ("dependencies_filtered", toJson false)]

syntax (name := qecExport) "#qec_export" "[" ident,* "]" : command

elab_rules : command
  | `(#qec_export [$names:ident,*]) => do
    let declarations ← names.getElems.mapM fun name => declarationJson name.getId
    let env ← getEnv
    let output := Json.mkObj [("schema_version", toJson "qecgraph.lean-export.v1"),
      ("exporter_version", toJson "lean-environment-v1"), ("lean_version", toJson Lean.versionString),
      ("declarations", Json.arr declarations), ("driver_imports", importsJson env.header.imports),
      ("imported_modules", namesJson env.allImportedModuleNames),
      ("environment_trust_level", toJson env.header.trustLevel.toNat),
      ("dependency_semantics", toJson "Direct type/value constants and unfiltered transitive ConstantInfo closure; not author uses edges"),
      ("axiom_method", toJson "Lean.collectAxioms on the actual checked environment"),
      ("type_expr_protocol", toJson "Lean.Expr structural JSON v1; nonsemantic metadata payloads omitted")]
    liftIO <| IO.println output.compress

end QEC.Export
