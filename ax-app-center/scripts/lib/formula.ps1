# 계산 열 수식의 작은 해석기. 오프라인 점검에서 "생성한 수식 문자열"이 7.1 표대로 등급을 내는지 확인한다.
# 지원 범위: IF, OR, AND, NOT, "문자열", [열], TRUE/FALSE, = 와 <> 비교. (등급 수식에 쓰는 것만)

function Invoke-AxFormula {
    param([Parameter(Mandatory)][string]$Formula, [Parameter(Mandatory)][hashtable]$Row)

    $src = $Formula.Trim()
    if ($src.StartsWith('=')) { $src = $src.Substring(1) }

    # 토큰화
    $tokens = [System.Collections.Generic.List[object]]::new()
    $i = 0
    while ($i -lt $src.Length) {
        $ch = $src[$i]
        if ([char]::IsWhiteSpace($ch)) { $i++; continue }
        if ($ch -eq '"') {
            $j = $src.IndexOf('"', $i + 1); if ($j -lt 0) { throw "닫히지 않은 문자열 (위치 $i)" }
            $tokens.Add(@{ T = 'str'; V = $src.Substring($i + 1, $j - $i - 1) }); $i = $j + 1; continue
        }
        if ($ch -eq '[') {
            $j = $src.IndexOf(']', $i + 1); if ($j -lt 0) { throw "닫히지 않은 열 참조 (위치 $i)" }
            $tokens.Add(@{ T = 'ref'; V = $src.Substring($i + 1, $j - $i - 1) }); $i = $j + 1; continue
        }
        if ($src.Substring($i).StartsWith('<>')) { $tokens.Add(@{ T = 'op'; V = '<>' }); $i += 2; continue }
        if ($ch -in '(', ')', ',', '=') { $tokens.Add(@{ T = 'p'; V = [string]$ch }); $i++; continue }
        $m = [regex]::Match($src.Substring($i), '^[A-Za-z]+')
        if ($m.Success) { $tokens.Add(@{ T = 'id'; V = $m.Value.ToUpperInvariant() }); $i += $m.Length; continue }
        throw "알 수 없는 문자 '$ch' (위치 $i)"
    }

    $state = @{ Pos = 0 }
    function Peek { if ($state.Pos -lt $tokens.Count) { $tokens[$state.Pos] } else { $null } }
    function Take([string]$v) {
        $t = Peek
        if (-not $t -or ($v -and $t.V -ne $v)) { throw "수식 해석 오류: '$v' 가 와야 함 (토큰 $($state.Pos))" }
        $state.Pos++; return $t
    }
    function ParseExpr {
        $left = ParseAtom
        $t = Peek
        if ($t -and ($t.V -eq '=' -or $t.V -eq '<>')) {
            $state.Pos++; $right = ParseAtom
            $eq = ([string]$left -eq [string]$right)
            return $(if ($t.V -eq '=') { $eq } else { -not $eq })
        }
        return $left
    }
    function ParseArgs {
        Take '(' | Out-Null
        $args2 = @()
        if ((Peek).V -ne ')') {
            while ($true) { $args2 += , (ParseExpr); if ((Peek).V -eq ',') { $state.Pos++ } else { break } }
        }
        Take ')' | Out-Null
        return , $args2
    }
    function ParseAtom {
        $t = Take $null
        switch ($t.T) {
            'str' { return $t.V }
            'ref' {
                if (-not $Row.ContainsKey($t.V)) { throw "수식이 참조한 열 값이 없음: [$($t.V)]" }
                return $Row[$t.V]
            }
            'id' {
                switch ($t.V) {
                    'TRUE' { return $true }
                    'FALSE' { return $false }
                    'IF' {
                        $a = ParseArgs
                        if ($a.Count -ne 3) { throw 'IF 인수는 3개' }
                        return $(if ([bool]$a[0]) { $a[1] } else { $a[2] })
                    }
                    'OR' { $a = ParseArgs; return [bool](@($a | Where-Object { [bool]$_ }).Count) }
                    'AND' { $a = ParseArgs; return (@($a | Where-Object { -not [bool]$_ }).Count -eq 0) }
                    'NOT' { $a = ParseArgs; return (-not [bool]$a[0]) }
                    default { throw "지원하지 않는 함수: $($t.V)" }
                }
            }
            default { throw "수식 해석 오류: 예상하지 못한 '$($t.V)'" }
        }
    }

    $result = ParseExpr
    if ($state.Pos -ne $tokens.Count) { throw "수식 해석 오류: 남은 토큰이 있음 (위치 $($state.Pos))" }
    return $result
}
