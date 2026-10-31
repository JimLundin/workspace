/* Demo backdrop: the code shown behind the glass in the "Dark app" surroundings. */
(function code() {
  const lines = [
    `<span class="k">from</span> dataclasses <span class="k">import</span> <span class="t">dataclass</span>`,
    `<span class="k">from</span> assistant.feed_origin <span class="k">import</span> <span class="t">App</span>`, ``,
    `<span class="c"># Glass has no colour of its own; tint carries meaning only.</span>`,
    `<span class="f">@dataclass</span>(<span class="v">frozen</span>=<span class="k">True</span>, <span class="v">slots</span>=<span class="k">True</span>)`,
    `<span class="k">class</span> <span class="t">Material</span>:`,
    `    <span class="v">fill</span>: <span class="t">float</span>`, `    <span class="v">blur</span>: <span class="t">float</span>`, `    <span class="v">rim</span>: <span class="t">float</span>`, ``,
    `<span class="k">def</span> <span class="f">material</span>(<span class="v">size</span>: <span class="t">Size</span>, <span class="v">look</span>: <span class="t">Look</span>) -> <span class="t">Material</span>:`,
    `    <span class="k">match</span> size, look:`,
    `        <span class="k">case</span> <span class="t">Size</span>.SMALL, <span class="t">Look</span>.CLEAR:`,
    `            <span class="k">return</span> <span class="t">Material</span>(<span class="n">0.20</span>, <span class="n">10</span>, <span class="n">0.9</span>)`,
    `        <span class="k">case</span> <span class="t">Size</span>.LARGE, <span class="t">Look</span>.CLEAR:`,
    `            <span class="k">return</span> <span class="t">Material</span>(<span class="n">0.66</span>, <span class="n">28</span>, <span class="n">0.9</span>)`,
    `        <span class="k">case</span> _, <span class="t">Look</span>.TINTED:`,
    `            <span class="k">return</span> <span class="t">Material</span>(<span class="n">0.86</span>, <span class="n">28</span>, <span class="n">0.6</span>)`, ``,
    `<span class="k">def</span> <span class="f">concentric</span>(<span class="v">outer</span>: <span class="t">float</span>, <span class="v">inset</span>: <span class="t">float</span>) -> <span class="t">float</span>:`,
    `    <span class="s">"""Nested corners share a centre."""</span>`,
    `    <span class="k">return</span> <span class="f">max</span>(<span class="n">0.0</span>, outer - inset)`, ``,
    `<span class="k">def</span> <span class="f">scheme_for</span>(<span class="v">luma</span>: <span class="t">float</span>) -> <span class="t">Scheme</span>:`,
    `    <span class="k">return</span> <span class="t">Scheme</span>.DARK <span class="k">if</span> luma &lt; <span class="n">0.5</span> <span class="k">else</span> <span class="t">Scheme</span>.LIGHT`,
  ];
  const all = [...lines, ...lines, ...lines];
  document.getElementById("src").innerHTML = all.join("\n");
  document.getElementById("gutter").textContent = all.map((_, i) => i + 1).join("\n");
})();

