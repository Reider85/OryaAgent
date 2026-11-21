"""Test fixtures for B-30 multi-language projects."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def java_project():
    """Create a temporary Java project for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)

        # Create basic Java project structure
        src_main_java = project_path / "src" / "main" / "java"
        src_main_java.mkdir(parents=True)

        src_test_java = project_path / "src" / "test" / "java"
        src_test_java.mkdir(parents=True)

        # Create pom.xml
        pom_xml = project_path / "pom.xml"
        pom_xml.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>test-project</artifactId>
    <version>1.0.0</version>
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
    </properties>
    <dependencies>
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter</artifactId>
            <version>5.8.2</version>
            <scope>test</scope>
        </dependency>
    </dependencies>
</project>""")

        # Create a simple Java class
        main_class = src_main_java / "Main.java"
        main_class.write_text("""package com.example;

public class Main {
    public static void main(String[] args) {
        System.out.println("Hello, World!");
    }

    public void greet(String name) {
        System.out.println("Hello, " + name + "!");
    }
}
""")

        # Create a test class
        test_class = src_test_java / "MainTest.java"
        test_class.write_text("""package com.example;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class MainTest {
    @Test
    void testGreet() {
        Main main = new Main();
        main.greet("World");
    }
}
""")

        yield project_path


@pytest.fixture
def rust_project():
    """Create a temporary Rust project for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)

        # Create basic Rust project structure
        src_dir = project_path / "src"
        src_dir.mkdir()

        # Create Cargo.toml
        cargo_toml = project_path / "Cargo.toml"
        cargo_toml.write_text("""[package]
name = "test-project"
version = "0.1.0"
edition = "2021"

[dependencies]
""")

        # Create main.rs
        main_rs = src_dir / "main.rs"
        main_rs.write_text("""fn main() {
    println!("Hello, World!");
}

fn greet(name: &str) -> String {
    format!("Hello, {}!", name)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_greet() {
        let result = greet("World");
        assert_eq!(result, "Hello, World!");
    }
}
""")

        yield project_path


@pytest.fixture
def go_project():
    """Create a temporary Go project for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)

        # Create basic Go project structure
        cmd_dir = project_path / "cmd" / "server"
        cmd_dir.mkdir(parents=True)

        pkg_dir = project_path / "pkg" / "handler"
        pkg_dir.mkdir(parents=True)

        # Create go.mod
        go_mod = project_path / "go.mod"
        go_mod.write_text("""module example.com/test-project

go 1.21

require (
)
""")

        # Create main.go
        main_go = cmd_dir / "main.go"
        main_go.write_text("""package main

import (
    "fmt"
    "example.com/test-project/pkg/handler"
)

func main() {
    fmt.Println("Hello, World!")
    handler.Greet("World")
}
""")

        # Create handler.go
        handler_go = pkg_dir / "handler.go"
        handler_go.write_text("""package handler

import "fmt"

func Greet(name string) {
    fmt.Printf("Hello, %s!\\n", name)
}
""")

        yield project_path


@pytest.fixture
def javascript_project():
    """Create a temporary JavaScript project for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)

        # Create basic JavaScript project structure
        src_dir = project_path / "src"
        src_dir.mkdir()

        # Create package.json
        package_json = project_path / "package.json"
        package_json.write_text("""{
  "name": "test-project",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "build": "echo 'Building...'",
    "test": "echo 'Testing...'",
    "lint": "echo 'Linting...'",
    "format": "echo 'Formatting...'"
  },
  "devDependencies": {
    "eslint": "^8.0.0",
    "prettier": "^2.0.0"
  }
}""")

        # Create a simple JavaScript file
        main_js = src_dir / "main.js"
        main_js.write_text("""function greet(name) {
    return `Hello, ${name}!`;
}

function main() {
    console.log("Hello, World!");
    console.log(greet("World"));
}

main();
""")

        # Create a test file
        test_js = src_dir / "main.test.js"
        test_js.write_text("""import { greet } from './main.js';

function testGreet() {
    const result = greet("World");
    console.log("Test passed:", result);
}

testGreet();
""")

        yield project_path


@pytest.fixture
def frontend_project():
    """Create a temporary Frontend project for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)

        # Create basic Frontend project structure
        src_dir = project_path / "src"
        src_dir.mkdir()

        public_dir = project_path / "public"
        public_dir.mkdir()

        # Create package.json
        package_json = project_path / "package.json"
        package_json.write_text("""{
  "name": "test-project",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "build": "echo 'Building...'",
    "test": "echo 'Testing...'",
    "lint": "echo 'Linting...'",
    "format": "echo 'Formatting...'"
  },
  "devDependencies": {
    "eslint": "^8.0.0",
    "prettier": "^2.0.0",
    "@typescript-eslint/parser": "^5.0.0",
    "@typescript-eslint/eslint-plugin": "^5.0.0",
    "eslint-plugin-react": "^7.0.0",
    "eslint-plugin-react-hooks": "^4.0.0"
  }
}""")

        # Create tsconfig.json
        tsconfig_json = project_path / "tsconfig.json"
        tsconfig_json.write_text("""{
  "compilerOptions": {
    "target": "es2020",
    "lib": ["dom", "dom.iterable", "es6"],
    "allowJs": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "esnext",
    "moduleResolution": "node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react"
  },
  "include": ["src"]
}""")

        # Create a simple React component
        app_tsx = src_dir / "App.tsx"
        app_tsx.write_text("""import React from 'react';

interface AppProps {
  name: string;
}

function App({ name }: AppProps) {
  return (
    <div>
      <h1>Hello, {name}!</h1>
      <button onClick={() => console.log('Button clicked')}>
        Click me
      </button>
    </div>
  );
}

export default App;
""")

        # Create a test file
        app_test_tsx = src_dir / "App.test.tsx"
        app_test_tsx.write_text("""import React from 'react';
import { render, screen } from '@testing-library/react';
import App from './App';

test('renders greeting', () => {
  render(<App name="World" />);
  const heading = screen.getByText(/Hello, World!/i);
  expect(heading).toBeInTheDocument();
});
""")

        yield project_path


@pytest.fixture
def multi_language_project():
    """Create a temporary multi-language project for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)

        # Create Java part
        java_src = project_path / "java" / "src" / "main" / "java"
        java_src.mkdir(parents=True)

        java_main = java_src / "Main.java"
        java_main.write_text("""package com.example;

public class Main {
    public static void main(String[] args) {
        System.out.println("Hello from Java!");
    }
}
""")

        # Create Rust part
        rust_src = project_path / "rust" / "src"
        rust_src.mkdir()

        rust_main = rust_src / "main.rs"
        rust_main.write_text("""fn main() {
    println!("Hello from Rust!");
}
""")

        # Create Go part
        go_src = project_path / "go" / "cmd" / "server"
        go_src.mkdir(parents=True)

        go_main = go_src / "main.go"
        go_main.write_text("""package main

import "fmt"

func main() {
    fmt.Println("Hello from Go!")
}
""")

        # Create JavaScript part
        js_src = project_path / "javascript" / "src"
        js_src.mkdir()

        js_main = js_src / "main.js"
        js_main.write_text("""function main() {
    console.log("Hello from JavaScript!");
}

main();
""")

        # Create Frontend part
        frontend_src = project_path / "frontend" / "src"
        frontend_src.mkdir()

        frontend_app = frontend_src / "App.tsx"
        frontend_app.write_text("""import React from 'react';

function App() {
  return (
    <div>
      <h1>Hello from Frontend!</h1>
    </div>
  );
}

export default App;
""")

        yield project_path


@pytest.fixture
def mixed_file_types():
    """Create a temporary directory with mixed file types for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)

        # Create various file types
        files = {
            "src/Main.java": "public class Main { }",
            "src/lib.rs": "fn main() { }",
            "src/main.go": "package main; func main() { }",
            "src/app.js": "function main() { }",
            "src/App.tsx": "import React from 'react'; function App() { }",
            "src/styles.css": ".container { }",
            "README.md": "# Test Project",
            "pom.xml": "<project></project>",
            "Cargo.toml": "[package]",
            "go.mod": "module test",
            "package.json": '{ "name": "test" }',
            "tsconfig.json": '{ "compilerOptions": {} }',
        }

        for file_path, content in files.items():
            full_path = project_path / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

        yield project_path
